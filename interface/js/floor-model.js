// What the Building and the Floor show, worked out from what the service returned: pure functions with no document and no
// network, so they run under a test. The inputs are the bodies of the reads kept in the City's snapshot (`projects`, and
// for each accepted project its `status` and `agents`) plus what the screens read for themselves (a task's body, the
// documents). Nothing is decided here: a count is a count of what came, a state is derived by the rule the specification
// gives (working: a task of the agent runs; off: the agent is disabled or its acting mode is `stopped`; waiting: it has an
// open decision; idle: none of these), and a word is the display word of a closed list. A decision on a request and a
// request itself have no agent: they belong to the planning agent, the Lobby.

import * as format from "./format.js";
import * as router from "./router.js";
import { MAX_FLOORS, acceptance, floorNumber, openRequests, pickRequest, requestChoice, routingRequest, routingWords } from "./model.js";
import { windowState } from "./scene/look.js";
import { waitLines, waitingLabel, waitsOf } from "./waits.js";

export const PLANNING = "planning";
const FINAL_REQUEST = new Set(["done", "cancelled"]);

// The closed list of an agent's modes (runtime/autonomy.py MODES), with the mode's one line (a page constant: the drawing's words).
export const MODES = Object.freeze(["stopped", "supervised", "milestones", "autonomous", "autonomous-with-policy"]);
export const PIPS = Object.freeze({ stopped: 0, supervised: 1, milestones: 2, autonomous: 3, "autonomous-with-policy": 4 });
export const MODE_LINES = Object.freeze({
  stopped: "Off, starts nothing",
  supervised: "Every review reaches you",
  milestones: "Reviews reach you at milestones, the rest are released when the skill is proven",
  autonomous: "Reviews are released when the skill is proven, effects still ask you",
  "autonomous-with-policy": "Like autonomous, and an effect inside an approved policy runs without asking",
});

// Display words of the closed lists (specification, "Display words"); an unknown value is shown as it came.
export const TASK_STATE = Object.freeze({
  requested: "Requested", planned: "Planned", ready: "Ready", running: "Running", waiting: "Waiting for you", blocked: "Blocked",
  done: "Done", failed: "Failed", cancelled: "Cancelled",
});
export const ENDING = Object.freeze({
  done: "Done", question: "Asked a question", draft_with_questions: "Wrote a draft and still has questions",
  gate: "Stopped at its confirmation gate", blocked: "Blocked, an input is missing", unclassified: "Ended in a way no rule recognises, read the reply",
});
export const FAILURE = Object.freeze({
  timeout: "Timed out", refused: "Refused", auth: "Credential refused", adapter: "The adapter failed", early_end: "Ended early",
  settings: "A setting is wrong", stopped: "Stopped", internal: "Internal error",
});
export const RUN_STATUS = Object.freeze({ running: "Running", ok: "Done", failed: "Failed" });
export const RESOLUTION = Object.freeze({
  approved: "approved", accepted: "accepted", released: "released", answered: "answered", rejected: "rejected", cancelled: "cancelled",
});

// The words of the two caps (A-20) are in format.js (the Control room's caps line and the KPI cards use them too).

// What a held ready task is waiting for, in the words of the dispatcher's closed list of reasons (runtime/dispatcher.py REASONS). A reason the
// page does not know is shown as it came.
export const HELD_SENTENCES = Object.freeze({
  stopped: "The agent is stopped, so it starts nothing.",
  "cap: runs per day": "The agent used all its runs for today.",
  "cap: usd per day": "The agent used all its spend for today.",
  credential: "The reference model's credential is not set.",
  "secret store": "The service cannot read the secret store.",
  image: "The eval image is not on this machine.",
  "dispatch off": "The service is not dispatching tasks.",
  "job running": "Another task of this project is running; one runs at a time.",
  waiting: "The task waits for another task; its reason is on its row.",
  "no enabled agent owns the task": "No enabled agent owns this task.",
  other: "The dispatcher held this task for a reason the page does not know.",
});

/** The sentence of a held reason. */
export function heldSentence(reason) {
  return HELD_SENTENCES[reason] !== undefined ? HELD_SENTENCES[reason] : String(reason || "");
}

const word = (table, key) => (table[key] !== undefined ? table[key] : (typeof key === "string" && key ? key : ""));

/** The words of a task state. */
export function taskWord(state) {
  return word(TASK_STATE, state);
}

/** The chip classes of a task or run state: running theme, waiting warn, done success, failed and blocked error, else muted. */
export function stateTone(state) {
  if (state === "running") return "pui-theme pui-soft";
  if (state === "waiting") return "pui-warn pui-soft";
  if (state === "done" || state === "ok") return "pui-success pui-soft";
  if (state === "failed" || state === "blocked") return "pui-error pui-soft";
  return "pui-muted pui-soft";
}

// --- numbers and times -----------------------------------------------------------------------------------------------------

/** "3.1 KB": 1 KB is 1024 bytes, one decimal; a number that is not a size is "". */
export function formatSize(bytes) {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** "2026-10-03 09:05" in the browser's time zone for an ISO stamp, or "". */
export function formatWhen(stamp) {
  const when = new Date(typeof stamp === "string" ? stamp : "");
  if (!Number.isFinite(when.getTime())) return "";
  const p = (n) => String(n).padStart(2, "0");
  return `${when.getFullYear()}-${p(when.getMonth() + 1)}-${p(when.getDate())} ${p(when.getHours())}:${p(when.getMinutes())}`;
}

/** Seconds under a minute ("42 s"), else "3 min 5 s"; unknown is "". */
export function formatDuration(ms) {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 0) return "";
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds} s`;
  return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
}

// --- who owns what ---------------------------------------------------------------------------------------------------------

const agentOf = (row) => (row && row.agent ? row.agent : PLANNING);

/** The tasks of an agent over every request, newest first: each {id, key, title, skill, state, note, agent, requestId}. */
export function agentTasks(status, name) {
  const out = [];
  for (const request of (status && Array.isArray(status.requests)) ? status.requests : []) {
    for (const t of Array.isArray(request.tasks) ? request.tasks : []) {
      if (agentOf(t) === name) out.push({ ...t, requestId: request.id });
    }
  }
  return out.sort((a, b) => b.id - a.id);
}

/** The open decisions of an agent, in the order the service gave (oldest first). */
export function agentDecisions(status, name) {
  return (Array.isArray(status && status.pending) ? status.pending : []).filter((item) => agentOf(item) === name);
}

/** The task a floor shows as current (OPEN-16): the running one, else the newest waiting, ready, blocked or failed one. */
export function pickCurrent(tasks) {
  for (const state of ["running", "waiting", "ready", "blocked", "failed"]) {
    const found = tasks.find((t) => t.state === state);
    if (found) return found;
  }
  return null;
}

/** The task that receives a handed-over file (OPEN-17): the newest failed or blocked task, else the current one, else null. */
export function handOverTarget(tasks, current) {
  return tasks.find((t) => t.state === "failed" || t.state === "blocked") || current || null;
}

/** The reason the dispatcher gives a ready task that only waits its turn, behind the one run at a time: it is queued, not held (M-24). */
export const TURN_REASON = "job running";

/**
 * How many ready tasks of an agent wait their turn behind the one run at a time and are not held (M-24, A-65): the agent's `queued` (its ready tasks) less the ones the last round
 * held for a reason of their own (`status.held`: a stopped agent, a cap, dispatch off, a wait on another task or request; the agent's own `held` count when the status lists none), never
 * under zero. A task held for `TURN_REASON` is waiting for its turn and so is queued. A held task keeps its reason and the idle look; a queued one that is free to start is "ready".
 */
export function queuedFree(agent, status) {
  const name = (agent && agent.name) || PLANNING;
  const listed = status && Array.isArray(status.held);
  const held = listed ? heldOf(status, name).filter((h) => h.reason !== TURN_REASON).length : format.count(agent && agent.held);
  return Math.max(0, format.count(agent && agent.queued) - held);
}

/** "working", "off", "waiting", "ready" or "idle" for an agent (the City's window rule first: a running task lights the floor; then a decision; then a task queued and not held). */
export function stateOf(agent, status, accepted = true) {
  if (!accepted) return "off";
  const name = agent.name || PLANNING;
  const requests = (status && Array.isArray(status.requests)) ? status.requests : [];
  const running = name === PLANNING ? requests.some((r) => r.state === "running" || r.routing) : agentTasks(status, name).some((t) => t.state === "running");
  if (running) return "working";
  if (agent.enabled === false || agent.acting_mode === "stopped") return "off";
  if (agentDecisions(status, name).length > 0) return "waiting";
  if (queuedFree(agent, status) > 0) return "ready";   // M-24: a task queued behind the one run at a time and not held: the owl is awake, ready
  return "idle";
}

const STATE_WORDS = { working: "Running", waiting: "Waiting for you", ready: "Queued", idle: "Idle", off: "Off, mode is stopped" };
export const QUEUED_NOTE = "starts when the current run ends";   // what a queued floor says where a sentence fits (M-24)
const DOT = { working: "theme", waiting: "warn", ready: "theme", idle: "muted", off: "border" };

/** The words of an agent's state, as the floors list reads them. */
export function stateWords(state) {
  return STATE_WORDS[state] || "";
}

// --- the Building ----------------------------------------------------------------------------------------------------------

function stub(agent) {
  return { name: agent, pack: null, enabled: true, mode: null, acting_mode: null, max_runs_per_day: 0, max_usd_per_day: 0, runs_today: 0, usd_today: 0, runs_without_cost: 0, queued: 0 };
}

/** The agents of a project in floor order (all of them: the planning agent first), and the stub of the Lobby when the project has none. */
export function floorAgents(detail) {
  const all = detail && Array.isArray(detail.agents) ? detail.agents.filter((a) => a && a.name) : [];
  const ordered = [...all.filter((a) => a.name === PLANNING), ...all.filter((a) => a.name !== PLANNING)];
  return ordered.length ? { list: ordered, none: false } : { list: [stub(PLANNING)], none: true };
}

/** The tasks of the request the tracking bar shows (the person's choice, else the newest with a running task, else the newest open): the work order's, used for each floor's done and left counts. */
function orderTasks(status, project = null) {
  const request = pickRequest(status, requestChoice(project));
  return request ? request.tasks || [] : [];
}

/** The held ready tasks of an agent, from the status body's `held` ([{task_id, agent, reason, at, next, commands: [{name, command}]}]); a task with no agent is the planning agent's. */
export function heldOf(status, name) {
  return (status && Array.isArray(status.held) ? status.held : []).filter((h) => (h.agent || PLANNING) === name);
}

/**
 * The commands a held task's reason needs, as the service gave them (`held[].commands`: [{name, command}], `command` null when no username is
 * registered): [{name, command}] with a command that is a text or null. Nothing is read out of the sentence `next`.
 */
export function heldCommands(held) {
  const list = held && Array.isArray(held.commands) ? held.commands : [];
  return list.filter((c) => c && typeof c === "object" && typeof c.name === "string" && c.name)
    .map((c) => ({ name: c.name, command: typeof c.command === "string" && c.command.trim() ? c.command : null }));
}

/**
 * The day's metered spend split in two for the meter (A-20): what was recorded and what is reserved for runs whose cost is not recorded
 * yet (the service gives both and their sum is usd_today), each as a share of the cap, the two never passing the track, and the words. An
 * entry with no split (an older service) is all recorded and has no note.
 */
export function spendSplit(agent, usd, usdCap) {
  const split = typeof agent.usd_reserved === "number";
  const usdReserved = split ? agent.usd_reserved : 0;
  const usdRecorded = typeof agent.usd_recorded === "number" ? agent.usd_recorded : usd - usdReserved;
  const recordedShare = format.share(usdRecorded, usdCap);
  const reservedShare = Math.min(format.share(usdReserved, usdCap), 1 - recordedShare);
  return { usdRecorded, usdReserved, usdRecordedShare: recordedShare, usdReservedShare: reservedShare, usdNote: split ? format.spendNote(usdRecorded, usdReserved) : "" };
}

/** One floor's row: every fact the plate, the list row and the tooltip show. */
export function floorRow(agent, status, context) {
  const name = agent.name || PLANNING;
  const lobby = name === PLANNING;
  const configured = context.accepted;
  const unaccepted = !configured && Boolean(context.kept);      // not accepted, and the last data read is shown (A-16)
  const accepted = configured || unaccepted;                      // whether there is data to show
  const state = stateOf(agent, status, accepted);
  const decisions = accepted ? agentDecisions(status, name).length : 0;
  const work = orderTasks(status, context.project).filter((t) => agentOf(t) === name);
  const done = work.filter((t) => t.state === "done").length;
  const running = work.filter((t) => t.state === "running").length;
  const left = work.filter((t) => t.state === "planned" || t.state === "blocked").length;       // A-12: not started and not ready
  const queued = format.count(agent.queued);
  // R-23b: the board of the room has one note for each task of the agent in the followed request, coloured by state: done, running, failed (the error tone) or still to do (a cancelled
  // task has none; every other state is still to do; the plate's "left" counts the planned and the blocked ones only, and the board's tooltip says that number)
  const notes = work.filter((t) => t.state !== "cancelled").map((t) => (t.state === "done" ? "done" : t.state === "running" ? "run" : t.state === "failed" ? "fail" : "left"));
  const waiters = work.filter((t) => waitsOf(t).length > 0);       // A-29: planned tasks that wait for another task or request (counted under "left")
  const waits = waiters.length
    ? { text: waiters.length === 1 ? waitingLabel(waiters[0]) : `${waiters.length} waiting`, title: waiters.flatMap((t) => waitLines(t).map((line) => `task #${t.id} ${line}`)).join("; ") } : null;
  const heldTasks = accepted ? heldOf(status, name) : [];
  const heldReason = heldTasks.length ? heldTasks[0].reason : null;
  const runs = format.count(agent.runs_today);
  const runsCap = format.count(agent.max_runs_per_day);
  const usd = format.count(agent.usd_today);
  const usdCap = format.count(agent.max_usd_per_day);
  const unknown = format.count(agent.runs_without_cost);
  const split = spendSplit(agent, usd, usdCap);
  const label = format.agentWord(name);
  const mode = agent.mode || null;
  const acting = agent.acting_mode || null;
  const stateWord = accepted ? STATE_WORDS[state] : "Waiting for the configuration to be accepted.";
  // R-26: the state as a soft badge: working (brand), resting and off (muted), waiting for you, held: ... and not accepted (warn)
  const plateWord = !configured ? "not accepted"
    : state === "working" ? "working" : state === "off" ? "Off, mode is stopped" : state === "waiting" ? "waiting for you" : state === "ready" ? "queued" : heldReason ? `held: ${heldReason}` : "resting";
  const plateTone = !configured ? "pui-warn" : state === "working" ? "pui-theme" : state === "off" ? "pui-muted" : (state === "waiting" || heldReason) ? "pui-warn" : "pui-muted";
  const lower = state === "working" ? "working" : state === "waiting" ? "waiting for you" : state === "ready" ? "queued" : state === "idle" ? "idle" : "off";
  const inUse = format.metersInUse(agent);        // A-38: a meter only for a cap in use
  const money = `${format.dollars(usd)} of ${format.dollars(usdCap)}`;
  const usage = [inUse.runs ? `${runs} of ${runsCap} runs` : "", inUse.spend ? money : ""].filter(Boolean);
  const meters = [inUse.runs ? `runs ${runs} / ${runsCap}` : "", inUse.spend ? money : ""].filter(Boolean).join(" · ");
  const counts = [`${done} done`, running > 0 ? `${running} running` : "", queued > 0 ? `${queued} queued` : "", `${left} left`, waits ? waits.text : ""].filter(Boolean).join(", ");
  return {
    name, label, lobby, number: context.number, state, stateWord, accepted,
    unaccepted, held: heldTasks.length, heldReason, inUse,   // R-21 extended (M-24): the window is lit while the agent works, waits or is ready (a queued task)
    window: windowState(configured && (state === "working" || state === "waiting" || state === "ready")), dot: DOT[state], decisions, queued, done, running, left, waits, notes,
    runs, runsCap, usd, usdCap, unknown, ...split, runsTotal: agent.runs_total_today === undefined ? null : format.count(agent.runs_total_today), mode, acting, pips: mode ? PIPS[mode] || 0 : 0, actingPips: acting ? PIPS[acting] || 0 : 0,
    actingDiffers: Boolean(mode && acting && mode !== acting),
    link: lobby ? router.lobbyHash(context.project) : router.floorHash(context.project, name),
    meters, counts,
    tip: `${label}: ${mode ? `${mode}, ` : ""}${lower}${inUse.runs ? `, ${runs} of ${runsCap} runs` : inUse.spend ? `, ${money}` : ""}`,
    linkName: `${label}, ${unaccepted ? `not accepted, ${lower}` : accepted ? lower : "waiting for the configuration to be accepted"}${heldReason ? `, held: ${heldReason}` : ""}${mode ? `, ${mode} mode` : ""}${usage.length ? `, ${usage.join(", ")}` : ""}${decisions ? `, ${format.decisions(decisions)} waiting` : ""}`,
    plateWord, plateTone, configured, modeLine: mode ? MODE_LINES[mode] || "" : "",
    // R-21: a floor whose agent waits is lit like one that works: its dot is the brand colour (the Floor's board keeps `dot`)
    plateDot: state === "waiting" ? "theme" : DOT[state],
    cardWord: configured ? STATE_WORDS[state] : "not accepted",
  };
}

/** The Building's data: {project, accepted, none, rows (bottom to top), more, tag, facts}. `now` is a Date (or null: the facts then leave out how long a run has lasted). */
export function building(snapshot, projectId, now = null) {
  const project = (snapshot.projects || []).find((p) => p.id === projectId) || null;
  if (!project) return null;
  const detail = snapshot.details[projectId] || null;
  const { accepted, kept } = acceptance(project, detail);
  const status = detail && detail.status ? detail.status : null;
  const { list, none } = floorAgents(detail);
  const ordered = list;
  const rows = ordered.map((agent) => floorRow(agent, status, { accepted, kept, project: projectId, number: floorNumber(ordered, agent.name || PLANNING) }));
  return {
    id: projectId, name: project.name, accepted, kept, none: none && (accepted || kept) && Boolean(status), rows, more: Math.max(0, rows.length - MAX_FLOORS), loaded: Boolean(status),
    tag: workOrder(status, rows, projectId), facts: facts(project, status, accepted, kept, now),
  };
}

/** The floor of the request's current task and the request's number: where the work-order tag rests (A6), or null. */
export function workOrder(status, rows, projectId = null) {
  const request = status ? pickRequest(status, requestChoice(projectId)) : null;
  if (!request) return null;
  const tasks = request.tasks || [];
  const current = tasks.find((t) => t.state === "running") || tasks.find((t) => t.state === "waiting") || null;
  if (!current) return null;
  const agent = agentOf(current);
  if (!rows.some((r) => r.name === agent)) return null;
  return { floor: agent, text: `#${request.id}`, request: request.id };
}

/**
 * The rows of the panel's "Requests (n)" (R-27, C-2): the open requests of the project, by number from the lowest as building.html lists them (the tracking bar's own list is newest first), each {id, title, state, tone, steps, name, selected, link,
 * cancellable, request}. `steps` is "2 of 6 steps done" and, when a task runs, " · now on Engineering" (the Lobby for the planning agent), else, when one waits for the
 * person, " · waiting for you". `selected` is the request the tracking bar shows. `request` is the row of the status body (the cancel dialog counts its tasks).
 */
export function requestRows(status, projectId) {
  const shown = status ? pickRequest(status, requestChoice(projectId)) : null;
  return [...openRequests(status)].sort((a, b) => a.id - b.id).map((request) => {
    const tasks = Array.isArray(request.tasks) ? request.tasks : [];
    const done = tasks.filter((t) => t.state === "done").length;
    const current = tasks.find((t) => t.state === "running") || tasks.find((t) => t.state === "waiting") || null;
    const now = request.routing && !(current && current.state === "running") ? "being routed" : current ? (current.state === "running" ? `now on ${format.agentWord(agentOf(current))}` : "waiting for you") : "";
    const title = request.title || `Request ${request.id}`;
    const state = typeof request.state === "string" ? request.state : "";
    const word = state ? state.charAt(0).toUpperCase() + state.slice(1) : "";
    const steps = `${done} of ${tasks.length} steps done${now ? ` · ${now}` : ""}`;
    return {
      id: request.id, title, state: word, tone: stateTone(state), steps, selected: Boolean(shown) && shown.id === request.id, link: router.requestHash(projectId, request.id),
      name: `Request ${request.id}, ${title}, ${word || state}, ${steps}`, cancellable: !FINAL_REQUEST.has(request.state) && !request.routing, request,   // A-51: the store refuses to cancel a request a run holds
    };
  });
}

/** The panel's facts: Configuration, Running now, Request, Waiting for you. */
export function facts(project, status, accepted, kept = false, now = null) {
  const out = { configuration: accepted ? "Accepted" : "Not accepted", accepted, running: null, request: null, waiting: 0 };
  if (kept) out.kept = true;
  if (!(accepted || kept) || !status) return out;
  const open = pickRequest(status, requestChoice(project.id));
  if (open) out.request = { id: open.id, title: open.title || "" };
  out.waiting = (status.pending || []).length;
  let id = project.running_task;
  if ((id === null || id === undefined) && kept) {
    // not accepted: the project list no longer says which task runs; the last status does
    const running = (status.requests || []).flatMap((r) => r.tasks || []).find((t) => t.state === "running");
    id = running ? running.id : null;
  }
  const routed = routingRequest(status);
  if ((id === null || id === undefined) && routed) {
    // A-51: no task runs while the router works on a request; the run row is the one record of it
    out.running = { id: routed.id, title: routed.title || "", link: router.requestHash(project.id, routed.id), label: routingWords(routed, now) };
    return out;
  }
  if (id !== null && id !== undefined) {
    let found = null;
    for (const request of status.requests || []) {
      if (request.id === id) found = { id, title: request.title || "", link: router.lobbyHash(project.id) };
      for (const t of request.tasks || []) {
        if (t.id === id) found = { id, title: t.title || t.key || "", link: t.agent && t.agent !== PLANNING ? router.floorHash(project.id, t.agent) : router.lobbyHash(project.id) };
      }
    }
    out.running = found || { id, title: "", link: router.buildingHash(project.id) };
  }
  return out;
}

/** The documents of an agent: the rows of `artifacts` whose `agent` is the agent (a project with no area agents: the Lobby's). */
export function agentDocuments(documents, name, none = false) {
  return (Array.isArray(documents) ? documents : []).filter((d) => (d.agent || (none ? PLANNING : null)) === name);
}

/** Drawers of a cabinet: ceil(documents / 4), from one to three. */
export function drawersOf(count) {
  return Math.max(1, Math.min(3, Math.ceil(count / 4)));
}

/** The plain data the plate of a row needs. */
export function plateOf(row, selected = false) {
  return {
    name: row.name, label: row.label, dot: row.plateDot, decisions: row.decisions, word: row.plateWord, tone: row.plateTone, modeLine: row.modeLine,
    actingLine: row.actingDiffers ? `acting as ${row.acting}` : "",
    done: row.done, running: row.running, left: row.left, queued: row.queued, waits: row.waits,
    inUse: row.inUse, runsText: `${row.runs} / ${row.runsCap}`, runsShare: format.share(row.runs, row.runsCap),
    usdText: `${format.dollars(row.usd)} / ${format.dollars(row.usdCap)}`, usdShare: format.share(row.usd, row.usdCap),
    unknown: row.unknown, usdReserved: row.usdReserved, usdNote: row.usdNote, usdRecordedShare: row.usdRecordedShare, usdReservedShare: row.usdReservedShare, runsTotal: row.runsTotal, mode: row.mode, pips: row.pips, acting: row.actingDiffers ? row.acting : null, actingPips: row.actingPips,
    selected, off: row.state === "off",
  };
}

/**
 * The compact floor card of a row (WP-9.8, the maintainer's design): the same fields in the same order for the card at the scene's
 * top right and for each row of the floors list: name (with its decisions badge), state word, mode plate, one line of runs and spend.
 */
export function cardOf(row) {
  // building.html at 375 px: the line is the runs and the spend alone; the note of what is recorded and reserved is its tooltip
  const runsLine = [row.inUse.runs ? `runs ${row.runs} / ${row.runsCap}` : "",
    row.inUse.spend ? `spend ${format.dollars(row.usd)} / ${format.dollars(row.usdCap)}` : ""].filter(Boolean).join(" · ");
  return {
    name: row.name, label: row.label, dot: row.plateDot, decisions: row.decisions, word: row.cardWord, tone: row.configured ? ({ working: "pui-theme", waiting: "pui-warn", ready: "pui-muted", idle: "pui-muted", off: "pui-muted" }[row.state]) : "pui-warn",
    mode: row.mode, modeLine: row.modeLine, pips: row.pips, acting: row.actingDiffers ? row.acting : null, actingPips: row.actingPips,
    runsLine: row.accepted ? runsLine : "", runsNote: row.accepted && row.inUse.spend ? format.costNote(row.usdNote, row.usdReserved, row.unknown) : "", off: row.state === "off",
  };
}

/**
 * The floors of a building for the world (scene/world.js): from the bottom, each with the sheets of its documents (up to six, each opens its
 * document), the drawers, the plate and the tooltip. `view` is building(...); documents the rows of `artifacts` (or null while unread).
 */
export function buildingScene(view, documents, { ready = true } = {}) {
  const selected = view.tag ? view.tag.floor : null;
  return {
    ready, selected, more: view.more, tag: view.tag,
    floors: view.rows.slice(0, MAX_FLOORS).map((row) => {
      const docs = agentDocuments(documents, row.name, view.none);
      return {
        name: row.name, label: row.label, state: row.state, window: row.window, decisions: row.decisions, lobby: row.lobby, notes: row.notes,
        // `null` while the documents are unread: the world keeps what the floor shows (an empty table on a first build) and changes it when they arrive
        sheets: documents === null ? null : docs.slice(0, 6).map((d) => ({ path: d.path, tip: d.path })), drawers: documents === null ? null : drawersOf(docs.length),
        documents: documents === null ? null : docs.length,   // R-23: one binder for each, sixteen to a bookcase
        tip: row.tip, interactive: true, plate: { ...plateOf(row, row.name === selected), tiny: view.more > 0 },   // R-25: with more than eight floors a plate is its name row alone
      };
    }),
  };
}

/** The canvas label of the Building. */
export function buildingLabel(view) {
  const waiting = view.rows.reduce((sum, r) => sum + r.decisions, 0);
  return `Building of ${view.name}, ${view.rows.length} floor${view.rows.length === 1 ? "" : "s"}, ${format.decisions(waiting)} waiting`;
}

// --- the Floor -------------------------------------------------------------------------------------------------------------

/** The three meters of the Agent tab; a meter whose cap is not in use for the project (`caps_in_use`, A-38) is null. */
export function meters(agent) {
  const inUse = format.metersInUse(agent);
  const runs = format.count(agent.runs_today);
  const runsCap = format.count(agent.max_runs_per_day);
  const usd = format.count(agent.usd_today);
  const usdCap = format.count(agent.max_usd_per_day);
  const unknown = format.count(agent.runs_without_cost);
  const split = spendSplit(agent, usd, usdCap);
  return {
    inUse,
    runsTotal: agent.runs_total_today === undefined ? null : `All runs today: ${format.count(agent.runs_total_today)}`,
    runs: !inUse.runs ? null : { label: format.METER_WORDS.runs, tip: format.METER_TIPS.runs, text: `${runs} / ${runsCap}`, share: format.share(runs, runsCap), full: runsCap > 0 && runs >= runsCap, name: `${format.METER_WORDS.runs} ${runs} / ${runsCap}` },
    spend: !inUse.spend ? null : { label: format.METER_WORDS.spend, tip: format.METER_TIPS.spend, text: `${format.dollars(usd)} / ${format.dollars(usdCap)}`, share: format.share(usd, usdCap), full: usdCap > 0 && usd >= usdCap, unknown: unknown > 0 ? `(+${unknown} of unknown cost)` : "", notes: format.costNote(split.usdNote, split.usdReserved, unknown),
      recorded: split.usdRecorded, reserved: split.usdReserved, recordedShare: split.usdRecordedShare, reservedShare: split.usdReservedShare, note: split.usdNote, name: `${format.METER_WORDS.spend} ${format.dollars(usd)} / ${format.dollars(usdCap)}` },
    queued: { text: String(format.count(agent.queued)), name: `Queued ${format.count(agent.queued)}` },
  };
}

/** The agent tab's state row: {tone, chip, line, off}. `running` is the running task's body (for "Running for 12 min", R-8: how long, not since when), or null; `now` is a Date. */
export function stateRow(state, decisions, runningBody, now = new Date()) {
  if (state === "working") {
    const runs = runningBody && Array.isArray(runningBody.runs) ? runningBody.runs : [];
    const lasted = runs.length ? format.runningFor(runs[runs.length - 1].started_at, now) : "";
    return { tone: "pui-theme pui-soft", chip: "Working", line: lasted ? `Running ${lasted}` : "Running", off: false };
  }
  if (state === "waiting") return { tone: "pui-warn pui-soft", chip: "Waiting for you", line: `${format.decisions(decisions)} in the Inbox`, off: false };
  if (state === "off") return { tone: "pui-muted pui-outline", chip: "Off", line: "Off, mode is stopped", off: true };
  if (state === "ready") return { tone: "pui-theme pui-soft", chip: "Queued", line: `Queued, ${QUEUED_NOTE}`, off: false };
  return { tone: "pui-muted pui-soft", chip: "Idle", line: "Waiting for the next task", off: false };
}

/**
 * What the current task's card says under its title (floor.html): the skill, then how long it has run ("for 12 min"), when a decision was asked ("asked 2 d ago"), when it was
 * queued ("queued 4 min ago"), or, for any other state, when it last changed ("3 h ago"); "" for the time when the page has no stamp. {skill, when}.
 */
export function currentSub(task, body, decisions, now) {
  const runs = body && Array.isArray(body.runs) ? body.runs : [];
  const run = runs.length ? runs[runs.length - 1] : null;
  const row = body && body.task ? body.task : {};
  const stamp = (typeof row.updated_at === "string" && row.updated_at) || (typeof row.created_at === "string" && row.created_at) || "";
  let when = "";
  if (task.state === "running") when = run ? format.runningFor(run.started_at, now) : "";
  else if (task.state === "waiting") {
    const asked = (Array.isArray(decisions) ? decisions : []).find((d) => d.task_id === task.id);
    when = asked && asked.created_at ? `asked ${format.agoPhrase(format.age(asked.created_at, now))}` : "";
  } else if (task.state === "ready") when = stamp ? `queued ${format.agoPhrase(format.age(stamp, now))}` : "";
  else when = stamp ? format.agoPhrase(format.age(stamp, now)) : "";
  return { skill: task.skill ? `skill ${task.skill}` : "", when };
}

/**
 * The rows of a run block: [{label, value, kind}] with kind "text", "code", "chip" or "wrap" (a wrapped mono line). The run is a
 * row of `runs[]` of a task body. Duration and Tokens are added (FLOW-8); a failed run shows its failure word in place of its ending.
 */
export function runRows(run) {
  const failed = run.status === "failed" || Boolean(run.failure);
  const rows = [
    { label: "Run", value: `#${run.id} ${run.skill || ""} ${run.skill_version || ""}`.replace(/\s+/g, " ").trim(), kind: "code" },
    { label: "Status", value: word(RUN_STATUS, run.status), kind: "chip", tone: stateTone(run.status) },
  ];
  if (failed) rows.push({ label: "Failure", value: run.failure ? word(FAILURE, run.failure) : "Failed", kind: "text" });
  else rows.push({ label: "Ending", value: run.ending ? word(ENDING, run.ending) : "-", kind: "text" });
  rows.push({ label: "Attempt", value: String(format.count(run.attempts)), kind: "text" });
  const duration = formatDuration(run.duration_ms);
  rows.push({ label: "Duration", value: duration || "-", kind: "text" });
  rows.push({ label: "Tokens", value: typeof run.tokens === "number" ? run.tokens.toLocaleString("en-US") : "-", kind: "text" });
  rows.push({ label: "Cost", value: typeof run.cost_usd === "number" ? `$${run.cost_usd.toFixed(4)}` : "unknown", kind: "text" });   // an unknown cost is never shown as a number (A-20)
  rows.push({ label: "Model", value: run.model || "-", kind: "code" });
  if (failed && run.error) rows.push({ label: "Error", value: String(run.error), kind: "wrap" });
  return rows;
}

/**
 * The Floor's data for an agent: null when the project is unknown, {found: false} when the agent is not in `agents`. The planning
 * agent has no floor of its own (its floor is the Lobby): it is found only when `options.lobby` is true, which the Lobby's tabs set.
 */
export function floor(snapshot, projectId, name, bodies = {}, options = {}) {
  const view = building(snapshot, projectId);
  if (!view) return null;
  const label = format.agentWord(name);
  if (!view.accepted && !view.kept) {
    const row = floorRow(stub(name), null, { accepted: false, project: projectId, number: null });
    return {
      found: true, notAccepted: true, view, row, tasks: [], others: [], decisions: [], runs: [], current: null, currentBody: null, target: null, runningBody: null,
      header: { title: `${label} agent`, sub: `${view.name} · Waiting for the configuration to be accepted`, icon: "building-2" },
      canvasLabel: `${label} floor of ${view.name}, not accepted`,
    };
  }
  const row = view.rows.find((r) => r.name === name);
  const detail = snapshot.details[projectId] || null;
  const status = detail && detail.status ? detail.status : null;
  if (!row || (name === PLANNING && !options.lobby)) return { found: false, view };
  const agent = (detail.agents || []).find((a) => a.name === name) || stub(name);
  const tasks = status ? agentTasks(status, name) : [];
  const current = pickCurrent(tasks);
  const decisions = status ? agentDecisions(status, name) : [];
  const currentBody = current ? bodies[current.id] || null : null;
  const runs = currentBody && Array.isArray(currentBody.runs) ? [...currentBody.runs].reverse() : [];
  const runningTask = tasks.find((t) => t.state === "running") || null;
  const subParts = [row.number === null ? null : `floor ${row.number}`, row.unaccepted ? "not accepted" : row.stateWord];     // C-6, floor.html: the project is in the crumbs and the switcher
  const holding = current && status ? heldOf(status, name).find((h) => h.task_id === current.id) : null;
  return {
    found: true, view, row, agent, tasks, current, others: tasks.filter((t) => !current || t.id !== current.id), decisions, runs, currentBody,
    unaccepted: Boolean(row.unaccepted),
    heldCurrent: holding ? { task_id: holding.task_id, reason: holding.reason, sentence: heldSentence(holding.reason), next: typeof holding.next === "string" && holding.next ? holding.next : null, ...(heldCommands(holding).length ? { commands: heldCommands(holding) } : {}) } : null,
    target: handOverTarget(tasks, current), runningBody: runningTask ? bodies[runningTask.id] || null : null,
    header: { title: `${row.label} agent`, sub: subParts.filter((p) => p !== null).join(" · "), icon: "building-2" },     // C-6; floor.html draws the building icon for every agent
    canvasLabel: `${row.label} floor of ${view.name}, ${row.label} agent ${row.accepted && !row.unaccepted ? { working: "working", waiting: "waiting", ready: "queued", idle: "idle", off: "off" }[row.state] : "not accepted"}, ${format.decisions(decisions.length)}`,
  };
}

/** Whether `projectId` has the Floor of area agent `name`: a project that is not accepted answers for every floor (its waiting line); an unknown project has none. */
export function hasFloor(snapshot, projectId, name) {
  const found = floor(snapshot, projectId, name);
  return Boolean(found && found.found);
}

/**
 * The wall board's content (R-32, floor.html): the title `#52 Implement the change · current task`, then the skill, the state and how long it has run (`for 12 min`, R-8), then the run:
 * its number and status, its ending (or failure) when it is over and says more than the status, its attempt, its tokens, and the cost, which reads `unknown` when it is not recorded
 * (C-18). `now` is a Date. Also the state dot colour.
 */
export function boardOf(view, now = new Date()) {
  const { row, current, currentBody } = view;
  if (!row.accepted) return { title: "Waiting for the configuration to be accepted.", lines: [], dot: "border" };
  if (row.state === "off" && !current) return { title: "Off, mode is stopped", lines: [], dot: "border" };
  if (!current) return { title: "No task yet", lines: ["This agent has no task yet."], dot: row.dot };
  const runs = currentBody && Array.isArray(currentBody.runs) ? currentBody.runs : [];
  const run = runs.length ? runs[runs.length - 1] : null;
  const lasted = current.state === "running" && run ? format.runningFor(run.started_at, now) : "";
  const lines = [`skill ${current.skill} · ${taskWord(current.state)}${lasted ? ` · ${lasted}` : ""}`];
  if (run) {
    const failed = run.status === "failed" || Boolean(run.failure);
    const status = word(RUN_STATUS, run.status);
    const ending = failed ? (run.failure ? word(FAILURE, run.failure) : "Failed") : (run.ending ? word(ENDING, run.ending) : "");
    lines.push([`run #${run.id} ${status}`, run.status !== "running" && ending && ending.toLowerCase() !== status.toLowerCase() ? ending : "", `attempt ${format.count(run.attempts)}`,
      typeof run.tokens === "number" ? `${run.tokens.toLocaleString("en-US")} tokens` : "", typeof run.cost_usd === "number" ? `$${run.cost_usd.toFixed(4)}` : "unknown"].filter(Boolean).join(" · "));
  }
  // the board names the task with its number and says it is the current one (C-18)
  const name = current.title || current.key || "";
  return { title: `#${current.id}${name ? ` ${name}` : ""} · current task`, lines, dot: row.state === "off" ? "border" : row.dot };
}

/** The words of the Floor's room (the world's `room`: tips and board). `documents` are the agent's rows of `artifacts`, newest first. */
export function roomScene(view, documents, ready = true, now = new Date()) {
  const board = boardOf(view, now);
  const row = view.row;
  const sheets = documents.slice(0, 6).map((d) => ({ path: d.path, tip: d.path }));
  const tasks = view.current ? `Current task · ${view.current.title || view.current.key}` : "Current task · none yet";
  return {
    ready, state: row.state, window: row.window, decisions: row.decisions, drawers: drawersOf(documents.length), sheets, documents: documents.length,
    tips: {
      agent: `${row.label} · ${row.state === "working" ? "working" : row.state === "waiting" ? "waiting for you" : row.state === "ready" ? `queued · ${QUEUED_NOTE}` : row.state === "off" ? "off" : "idle"}`,
      desk: tasks, tray: `Inbox · ${row.decisions} waiting`, cabinet: `${documents.length} document${documents.length === 1 ? "" : "s"} · open the Desk tab`,
      board: board.lines[0] || board.title,
    },
    board,
  };
}

// --- the Desk --------------------------------------------------------------------------------------------------------------

// What the Desk says a file is (A-33), from `artifacts[].kind`; a kind the page does not know (an older service gives none) is not shown.
const DESK_KINDS = Object.freeze({ text: "text", markdown: "Markdown", image: "image", other: "other" });

/** The Desk's word for a file's kind, or "". */
export function deskKind(kind) {
  return typeof kind === "string" && Object.prototype.hasOwnProperty.call(DESK_KINDS, kind) ? DESK_KINDS[kind] : "";
}

/** The rows of the Desk table: newest `modified_at` first, filtered by a case-insensitive substring of path or owner skill. */
export function deskRows(documents, filter = "") {
  const text = String(filter || "").trim().toLowerCase();
  return [...documents]
    .sort((a, b) => (a.modified_at < b.modified_at ? 1 : a.modified_at > b.modified_at ? -1 : a.path < b.path ? -1 : 1))
    .filter((d) => !text || String(d.path).toLowerCase().includes(text) || String(d.owner || "").toLowerCase().includes(text))
    .map((d) => ({ path: d.path, owner: d.owner || "", agent: d.agent || "", size: formatSize(d.size), kind: deskKind(d.kind), modified: formatWhen(d.modified_at), bound: Boolean(d.bound) }));
}

/** A path as the segments a break may follow ("/", "-" and "."), so a name is never broken inside a word. */
export function pathParts(path) {
  return String(path).split(/(?<=[/.-])/);
}

/** True when a path may be opened from a card: a returned path under docs/. */
export function openable(path) {
  return typeof path === "string" && path.startsWith("docs/") && !path.includes("..");
}

// --- the Inbox -------------------------------------------------------------------------------------------------------------

/**
 * What the person saved with a decision (A-41): {label, text} from the `answer` the `task` read carries, or null when no text was saved. A question
 * answered is "Your answer", a review or an effect answered "Your comment", any decision rejected "Your note". A release, an approval and a
 * cancellation save no text the person sees. The text is returned as it was typed; the Inbox draws it as plain text.
 */
function saidOf(item, resolution) {
  const text = typeof item.answer === "string" ? item.answer : "";
  if (!text.trim()) return null;
  if (resolution === "rejected") return { label: "Your note", text };
  if (resolution === "answered") return { label: item.kind === "question" ? "Your answer" : "Your comment", text };
  return null;
}

/** The resolved lines of an agent's tasks: from the `pending` of each `task` body that is not open, newest first; `said` is saidOf; `icon` is the outcome's (a check, or a cross for a rejection or a cancellation, R-38). */
export function resolvedLines(bodies, taskIds, now, limit = 8) {
  const out = [];
  for (const id of taskIds) {
    const body = bodies[id];
    for (const item of (body && Array.isArray(body.pending)) ? body.pending : []) {
      if (item.status === "open") continue;
      const resolution = item.resolution || (item.status === "cancelled" ? "cancelled" : "");
      const rejected = resolution === "rejected" || resolution === "cancelled";
      out.push({
        id: item.id, kind: item.kind, resolution, text: `${format.kindWord(item.kind)} ${word(RESOLUTION, resolution) || "resolved"}`,
        tone: rejected ? "pui-muted pui-soft" : "pui-success pui-soft", icon: rejected ? "x" : "check", title: item.title || "", stamp: item.resolved_at || item.created_at || "",
        age: format.age(item.resolved_at || item.created_at, now), when: formatWhen(item.resolved_at || item.created_at),
        said: saidOf(item, resolution),
      });
    }
  }
  return out.sort((a, b) => (a.stamp < b.stamp ? 1 : a.stamp > b.stamp ? -1 : b.id - a.id)).slice(0, limit);
}

/** "Agent" with no count, "Inbox, 2 decisions", "Desk, 12 documents": the tabs' accessible names. */
export function tabNames(decisions, documents) {
  return {
    agent: "Agent",
    inbox: decisions > 0 ? `Inbox, ${format.decisions(decisions)}` : "Inbox",
    desk: documents > 0 ? `Desk, ${documents} document${documents === 1 ? "" : "s"}` : "Desk",
  };
}
