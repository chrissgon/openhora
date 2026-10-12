// What the City shows, worked out from what the service returned: pure functions with no document and no network, so
// they run under a test. The inputs are the bodies of the service's reads, kept in one snapshot:
//   projects  the `projects` list: [{id, name, config: {accepted}, message?, open_pending?, running_task?}]
//   details   {[projectId]: {status, agents}}: the `status` body (its task rows carry `title` and `agent`, its pending
//             decisions carry `agent`) and the `agents` array of an accepted project
//   tasks     {["<projectId>:<taskId>"]: the `task` body {task, runs, pending}}: only the running task of the followed
//             project's open request, for the time its run started (`status` has no run)
// Nothing is decided here: a count is a count of what came, a state is the service's own word. A decision on a request
// (a plan, a router question) and a request itself have no agent: they belong to the planning agent, the Lobby.

import * as format from "./format.js";
import * as router from "./router.js";
import { windowState } from "./scene/look.js";
import { waitLines, waitingLabel, waitsOf } from "./waits.js";

export const MAX_LOTS = 4;       // at most four lots are drawn (EDGE-9); the rest are reached from the lists
export const MAX_FLOORS = 8;
const FINAL = new Set(["done", "cancelled"]);

/** The key of a task in the snapshot's `tasks`. */
export function taskKey(project, id) {
  return `${project}:${id}`;
}

/** The agents of a project in floor order: the planning agent first (the Lobby, floor 0), then the others in the order given. */
export function floorsOf(agents) {
  const list = Array.isArray(agents) ? agents : [];
  const planning = list.filter((a) => a && a.name === "planning");
  const others = list.filter((a) => a && a.name !== "planning");
  return [...planning, ...others].slice(0, MAX_FLOORS);
}

/** The number a floor is called: the planning agent is floor 0 when there is one, else the first agent is floor 1. */
export function floorNumber(ordered, name) {
  const index = ordered.findIndex((a) => a.name === name);
  if (index < 0) return null;
  return ordered.some((a) => a.name === "planning") ? index : index + 1;
}

/** Every row of every request of a status body: the requests and their tasks, each as {id, state, ...}. */
function rowsOf(status) {
  const out = [];
  for (const request of (status && Array.isArray(status.requests)) ? status.requests : []) {
    out.push({ ...request, tasks: undefined, request: true });
    for (const t of Array.isArray(request.tasks) ? request.tasks : []) out.push({ ...t, request: false, requestId: request.id });
  }
  return out;
}

/** The reason the dispatcher gives a ready task that only waits its turn behind the one run at a time: it is queued, not held (M-24). */
export const TURN_REASON = "job running";

/**
 * How many ready tasks of an agent wait their turn and are free to start (M-24, A-65): the agent's `queued` (its ready tasks) less what the page can tell keeps them from starting: the
 * tasks the last round held for a reason of its own (`status.held`, not `TURN_REASON`; the agent's own `held` count when the status lists none), the ready tasks that have an open wait
 * (the status rows), and all of them while the agent is at a daily cap in use (runs or spend, by its billing as the meters read it). The limit: while a run is in progress the dispatcher
 * reports every ready task as `TURN_REASON`, so a hold of another kind is known after the run, not during it. Never under zero.
 */
export function queuedFree(agent, status) {
  const name = (agent && agent.name) || "planning";
  const use = format.metersInUse(agent);
  const runsCap = format.count(agent && agent.max_runs_per_day);
  const usdCap = format.count(agent && agent.max_usd_per_day);
  if ((use.runs && runsCap > 0 && format.count(agent.runs_today) >= runsCap) || (use.spend && usdCap > 0 && format.count(agent.usd_today) >= usdCap)) return 0;
  const queued = format.count(agent && agent.queued);
  const listed = status && Array.isArray(status.held);
  const heldOwn = listed ? status.held.filter((h) => (h.agent || "planning") === name && h.reason !== TURN_REASON) : [];
  const own = listed ? heldOwn.length : format.count(agent && agent.held);
  const heldIds = new Set(heldOwn.map((h) => h.task_id));
  const waiting = rowsOf(status).filter((r) => !r.request && r.state === "ready" && (r.agent || "planning") === name && !heldIds.has(r.id) && waitsOf(r).length > 0).length;
  return Math.max(0, queued - own - waiting);
}

/**
 * The request a run of the planning agent's router holds now (A-51): the request row of a status body whose `routing` is set, or null. One run at a
 * time per project, so at most one. A request that is routed holds no task, so no task of the status is running while it is. A reroute of a
 * delivery holds a planned or done request: the search takes every request, final or not.
 */
export function routingRequest(status) {
  return (status && Array.isArray(status.requests) ? status.requests : []).find((r) => r && r.routing) || null;
}

/** The words of that run: "Planning agent · routing request #2 · for 3 min" (the last part only when `now` is given and the start time is known). */
export function routingWords(request, now = null) {
  const lasted = now && request.routing ? format.runningFor(request.routing.started_at, now) : "";
  return `Planning agent · routing request #${request.id}${lasted ? ` · ${lasted}` : ""}`;
}

/** The newest request that is not final (done or cancelled) of a status body, or null. */
export function openRequest(status) {
  const open = (status && Array.isArray(status.requests) ? status.requests : []).filter((r) => !FINAL.has(r.state));
  if (!open.length) return null;
  return open.reduce((a, b) => (b.id > a.id ? b : a));
}

/** The open (not final) requests of a status body, newest first. */
export function openRequests(status) {
  const open = (status && Array.isArray(status.requests) ? status.requests : []).filter((r) => !FINAL.has(r.state));
  return open.sort((a, b) => b.id - a.id);
}

/**
 * The request the tracking bar shows: the person's choice while that request is still open, else the newest open request that has a
 * running task, else the newest open request, else null (WP-9.8, the maintainer's rule).
 */
export function pickRequest(status, choice = null) {
  const open = openRequests(status);
  if (!open.length) return null;
  const chosen = choice === null || choice === undefined ? null : open.find((r) => r.id === choice);
  if (chosen) return chosen;
  return open.find((r) => (r.tasks || []).some((t) => t.state === "running") || r.routing) || open[0];
}

/** The request after (delta 1) or before (delta -1) `currentId` in the newest-first list, wrapping round; null when none is open. */
export function cycleRequest(status, currentId, delta) {
  const open = openRequests(status);
  if (!open.length) return null;
  const at = open.findIndex((r) => r.id === currentId);
  const next = at < 0 ? 0 : (at + delta + open.length) % open.length;
  return open[next];
}

// The person's choice of request for each project, kept in memory for the session (nothing is stored).
const choices = new Map();

/** Remember which request the tracking bar shows for a project. */
export function chooseRequest(projectId, requestId) {
  choices.set(projectId, requestId);
}

/** The remembered choice for a project, or null. */
export function requestChoice(projectId) {
  return choices.has(projectId) ? choices.get(projectId) : null;
}

/** Forget every choice (a new session). */
export function resetRequestChoices() {
  choices.clear();
}

/** The tasks whose `task` body the page needs: {project, id, state}. Only the running task of the followed project's shown request (its run's start time). */
export function neededTasks(projects, details, followed) {
  const wanted = [];
  for (const p of projects) {
    if (p.id !== followed) continue;
    const request = pickRequest(details[p.id] && details[p.id].status, requestChoice(p.id));
    const running = request && (request.tasks || []).find((t) => t.state === "running");
    if (running) wanted.push({ project: p.id, id: running.id, state: running.state });
  }
  return wanted;
}

/** The decisions of one project, each with the agent that owns it ("planning" for a decision on a request). */
function decisionsOf(status) {
  return (Array.isArray(status && status.pending) ? status.pending : []).map((item) => ({ item, agent: item.agent || "planning" }));
}

/**
 * Whether a project's configuration is accepted, and whether the page still holds data it read before it stopped being accepted (A-16):
 * {accepted, kept}. `kept` is true only when it is not accepted and a status was read; the screens then show that data, dimmed.
 */
export function acceptance(project, detail) {
  const accepted = Boolean(project && project.config && project.config.accepted) && !(detail && detail.error && detail.error.status === 412);
  return { accepted, kept: !accepted && Boolean(detail && detail.status) };
}

/**
 * Whether the City dims its two KPI cards and the tracking bar (round 4, city.html "A project not accepted"): when any project the service lists is not
 * accepted, whichever one is followed, because the cards' sums span every project and the band names the one that is not accepted.
 */
export function cityDims(projects, details) {
  return (Array.isArray(projects) ? projects : []).some((p) => !acceptance(p, details && details[p.id]).accepted);
}

/** The number of ready tasks the last dispatcher round held, from the status body (`held`: [{task_id, agent, reason, ...}]). */
export function heldCount(status) {
  return status && Array.isArray(status.held) ? status.held.length : 0;
}

/** One building of the City from a project, its status, its agents and the loaded tasks. */
export function buildingOf(project, detail) {
  const { accepted, kept } = acceptance(project, detail);
  const shown = accepted || kept;     // a project that is not accepted keeps the floors and the windows it had
  const ordered = floorsOf(detail && detail.agents);
  const status = detail && detail.status;
  const decided = decisionsOf(status);
  const running = new Set();
  for (const r of rowsOf(status)) {
    if (r.request && r.routing) running.add("planning");      // A-51: the router's run lights the Lobby's window like a task that runs
    if (r.state !== "running") continue;
    running.add(r.request ? "planning" : r.agent || "planning");
  }
  const waits = new Set(decided.map((d) => d.agent));
  const floors = (ordered.length ? ordered : [{ name: null, enabled: true, acting_mode: null }]).map((a) => {
    // R-21: a window is lit when the floor's agent is active, running a task or waiting for an answer, and dark otherwise (idle, stopped, not accepted)
    const active = a.enabled !== false && a.acting_mode !== "stopped";   // a stopped or disabled agent is off, whatever it asked (`floor-model.stateOf` says the same)
    // M-24: a queued task that is not held also lights the window (the agent is ready); the same count the floors make (`queuedFree` above)
    const ready = active && queuedFree(a, status) > 0;
    const window = windowState(accepted && Boolean(a.name) && (running.has(a.name) || ((waits.has(a.name) || ready) && active)));
    return { agent: a.name, window, waits: shown && (a.name ? waits.has(a.name) : decided.length > 0) };
  });
  const open = !shown ? 0 : status ? decided.length : format.count(project.open_pending);
  const runningTask = shown && project.running_task !== null && project.running_task !== undefined ? project.running_task : null;
  const routing = shown && Number.isInteger(project.routing_request) ? project.routing_request : null;      // A-51: the request a router run holds
  return { id: project.id, name: project.name, accepted, kept, floors, decisions: open, runningTask, routing, held: shown ? heldCount(status) : 0, message: project.message || "" };
}

/** What runs in a building: "task #5 running", "routing request #2" (the router's run, A-51) or "no task running". */
function runWords(building) {
  if (building.runningTask !== null) return `task #${building.runningTask} running`;
  return building.routing !== null && building.routing !== undefined ? `routing request #${building.routing}` : "no task running";
}

/** The tooltip sentence of a building (the specification's). */
export function tooltipOf(building) {
  if (!building.accepted) return `${building.name}: not accepted yet`;
  const running = runWords(building);
  return `${building.name}: ${format.decisions(building.decisions)} waiting, ${running}${building.held > 0 ? `, ${building.held} held` : ""}`;
}

/** The sub line of a building's label card. */
export function subOf(building) {
  if (!building.accepted) return "not accepted yet";
  return runWords(building);
}

/** The name a link to a building carries for a screen reader. */
export function linkNameOf(building) {
  if (!building.accepted) return `${building.name}, not accepted yet`;
  return `${building.name}, ${format.decisions(building.decisions)} waiting, ${runWords(building)}${building.held > 0 ? `, ${building.held} held` : ""}`;
}

/** The City's data in one value: its buildings, the waiting rows and the canvas label. */
export function city(snapshot, now) {
  const projects = Array.isArray(snapshot.projects) ? snapshot.projects : [];
  const buildings = projects.map((p) => buildingOf(p, snapshot.details[p.id]));
  const waiting = waitingRows(snapshot, now);
  const canvasLabel = projects.length
    ? `City with ${projects.length} project${projects.length === 1 ? "" : "s"}, ${waiting.length} decision${waiting.length === 1 ? "" : "s"} waiting`
    : "City with no project";
  return { buildings, waiting, canvasLabel };
}

/**
 * The sums the three KPI cards show for one scope: `projectId` null is every project (the City). `inUse` says which of the two meter cards mean
 * something (A-38): a cap is in use when any agent of the scope has it in use (`caps_in_use`); a scope with no agent shows both.
 */
export function kpiSums(snapshot, projectId) {
  const projects = (snapshot.projects || []).filter((p) => projectId === null || p.id === projectId);
  const sums = { decisions: 0, runs: 0, runsCap: 0, usd: 0, usdCap: 0, usdRecorded: 0, usdReserved: 0, runsTotal: 0, inUse: { runs: false, spend: false } };
  let agents = 0;
  for (const p of projects) {
    const detail = snapshot.details[p.id];
    sums.decisions += detail && detail.status ? (detail.status.pending || []).length : 0;
    for (const a of (detail && Array.isArray(detail.agents)) ? detail.agents : []) {
      const use = format.metersInUse(a);
      sums.inUse = { runs: sums.inUse.runs || use.runs, spend: sums.inUse.spend || use.spend };
      agents += 1;
      sums.runs += format.count(a.runs_today);
      sums.runsCap += format.count(a.max_runs_per_day);
      sums.usd += format.count(a.usd_today);
      sums.usdReserved += format.count(a.usd_reserved);
      sums.usdRecorded += typeof a.usd_recorded === "number" ? a.usd_recorded : format.count(a.usd_today) - format.count(a.usd_reserved);
      sums.runsTotal += format.count(a.runs_total_today);
      sums.usdCap += format.count(a.max_usd_per_day);
    }
  }
  if (!agents) sums.inUse = { runs: true, spend: true };
  return sums;
}

/**
 * The rows of "Waiting for you": every open decision of the given projects (all when `only` is null), oldest first. A row opens the card that
 * answers the decision; the row of a plan opens the Conversation at its request's line (C-2, J-6), where the plan card stands.
 */
export function waitingRows(snapshot, now, only = null) {
  const rows = [];
  for (const p of snapshot.projects || []) {
    if (only !== null && p.id !== only) continue;
    const status = snapshot.details[p.id] && snapshot.details[p.id].status;
    for (const { item, agent } of decisionsOf(status)) {
      const lobby = agent === "planning";
      const request = lobby && item.kind === "plan" && Number.isInteger(item.task_id) ? item.task_id : null;
      const link = request !== null ? router.requestHash(p.id, request)
        : lobby ? router.lobbyHash(p.id, "inbox", item.id) : router.floorHash(p.id, agent, "inbox", item.id);
      const kind = format.kindWord(item.kind);
      const where = `${p.name} · ${format.agentWord(agent)}`;
      rows.push({
        project: p.id, id: item.id, kind, title: item.title || "", where, link, createdAt: item.created_at || "",
        age: format.age(item.created_at, now),
        name: `${kind}, ${item.title || ""}, ${p.name}, ${format.agentWord(agent)}${item.created_at ? `, waiting ${format.ageWords(item.created_at, now)}` : ""}`,
      });
    }
  }
  rows.sort((a, b) => (a.createdAt < b.createdAt ? -1 : a.createdAt > b.createdAt ? 1 : a.id - b.id));
  return rows;
}

/** The steps of a request and what is "Now on": {request, steps, doneCount, now}, or null when no request is open. */
export function tracking(snapshot, projectId, now) {
  const project = (snapshot.projects || []).find((p) => p.id === projectId);
  const detail = project && snapshot.details[project.id];
  const request = detail ? pickRequest(detail.status, requestChoice(projectId)) : null;
  if (!project || !request) return null;
  const ordered = floorsOf(detail.agents);
  const tasks = request.tasks || [];
  const steps = tasks.map((t) => {
    const agent = t.agent || null;               // null: the project has no area agents
    const title = t.title || t.key;
    const word = agent ? format.agentWord(agent) : "";
    return {
      id: t.id, state: t.state, title, agent,
      sub: [word, waitingLabel(t)].filter(Boolean).join(" · "),      // the agent, and what the task waits for; no state word, the icon carries the state (R-8)
      ...(waitLines(t).length ? { waits: waitLines(t) } : {}),
      link: !agent || agent === "planning" ? router.lobbyHash(project.id) : router.floorHash(project.id, agent),
      name: `${title}, ${word ? `${word}, ` : ""}${t.state}${waitingLabel(t) ? `, ${waitingLabel(t)}` : ""}`,
    };
  });
  const current = steps.find((s) => s.state === "running") || steps.find((s) => s.state === "waiting") || null;
  let nowCard = null;
  if (current && !(request.routing && current.state !== "running")) {      // a router run on the request wins over a step that only waits (a delivery routed again)
    const body = snapshot.tasks[taskKey(project.id, current.id)];
    const floor = current.agent ? floorNumber(ordered, current.agent) : null;
    const running = current.state === "running";
    const runs = (body && Array.isArray(body.runs)) ? body.runs : [];
    const lasted = runs.length ? format.runningFor(runs[runs.length - 1].started_at, now) : "";
    const open = (detail.status.pending || []).filter((p) => p.task_id === current.id).length;
    nowCard = {
      where: `${running ? "Now on" : "Waiting on"}${floor === null ? "" : ` floor ${floor}`}${current.agent ? ` · ${current.agent === "planning" ? "lobby" : current.agent}` : ""}`,
      title: current.title, state: running ? "Running" : "Waiting for you", running,
      sub: `task #${current.id}${running ? (lasted ? ` · ${lasted}` : "") : ` · ${format.decisions(open)}`}`,
      link: current.link,
    };
  } else if (request.routing) {
    // A-51: the router works on the request: no task runs, the run row is the one record of it
    const floor = floorNumber(ordered, "planning");
    const lasted = format.runningFor(request.routing.started_at, now);
    nowCard = {
      where: `Now on${floor === null ? "" : ` floor ${floor}`} · lobby`, title: routingWords(request), state: "Running", running: true,
      sub: lasted || "just started", link: router.requestHash(project.id, request.id),
    };
  }
  const others = openRequests(detail.status).map((r) => ({
    id: r.id, title: r.title || `Request ${r.id}`, state: r.state, running: (r.tasks || []).some((t) => t.state === "running") || Boolean(r.routing), selected: r.id === request.id,
  }));
  return {
    request: { id: request.id, title: request.title || "", state: request.state, project: project.name, projectId: project.id },
    requests: others,
    steps, doneCount: tasks.filter((t) => t.state === "done").length, total: tasks.length, now: nowCard,
  };
}

/** The sub line of a project in the switcher: "Request #14 · 2 of 6 steps done", "No request is open" or "..." while unknown. */
export function projectSub(snapshot, projectId) {
  const project = (snapshot.projects || []).find((p) => p.id === projectId);
  if (!project) return "";
  if (!(project.config && project.config.accepted)) return "Not accepted";
  const detail = snapshot.details[projectId];
  if (!detail || !detail.status) return "...";
  const request = pickRequest(detail.status, requestChoice(projectId));
  if (!request) return "No request is open";
  const tasks = request.tasks || [];
  return `Request #${request.id} · ${tasks.filter((t) => t.state === "done").length} of ${tasks.length} steps done`;
}

/** The state of a screen's data: "loading" before the first read has answered, "error" when it failed and nothing was ever read, else "ready" (a later failure keeps the last data, dimmed). */
export function screenState(snapshot, failure) {
  if (snapshot.loaded) return "ready";
  return failure ? "error" : "loading";
}

/** Whether the City says the service has no project: only when a read answered and the list was empty. */
export function emptyCityVisible(state, buildingCount) {
  return state === "ready" && buildingCount === 0;
}
