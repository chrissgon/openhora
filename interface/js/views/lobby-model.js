// What the Lobby shows, worked out from what the service returned: pure functions with no document and no network, so
// they run under a test. Nothing is decided here: a request's state and a decision's actions are the service's own words.

import * as format from "../format.js";
import { drawersOf, stateTone } from "../floor-model.js";
import { windowState } from "../scene/look.js";

export const POLL_BUSY_MS = 2000;     // the conversation is read every 2 seconds while a `say` job runs; otherwise only when the page reloads
export const JOB_EVERY_MS = 1000;     // pollJob's period
export const MAX_BODIES = 8;          // the requests whose decisions are read with `task`: the newest few
export const MAX_INBOX_BODIES = 50;   // P-6: with the Inbox open, the requests whose bodies are read: those with a decision open, then the newest, up to this many
export const RESOLVED_LINES = 50;     // P-6: the resolved lines the Inbox lists, newest first

// R-43 (C-6): Conversation, Inbox, Tasks, Desk, Agent
export const TABS = Object.freeze([["conversation", "Conversation"], ["inbox", "Inbox"], ["tasks", "Tasks"], ["desk", "Desk"], ["agent", "Agent"]]);

// R-45: the hint under the field; the second hint (`/new --after`) is gone, since "After request" is a field of the form (R-46)
export const HINT = "Type / to list the commands.";
// A-23: while a run is in progress a plain line is stored and routed by the service when the run ends; the commands answer at once.
export const RUN_LINE = "A run is in progress: your line will be routed when it ends; a question about the state is answered now.";
export const QUEUED_WORD = "queued";
// Route it on a request while a run holds the project (another request being routed, or a task that runs): the service does not refuse it, it queues it (A-23)
export const QUEUE_REASON = "A run is in progress: this request is routed when it ends.";
export const QUEUED_NOTICE = Object.freeze({ tone: "info", title: "Recorded", text: "A run is in progress. The request is recorded and will be routed when the run ends." });
export const SENDING_TEXT = "The planning agent is working on this turn. It can take minutes.";
export const BUSY_NOTICE = Object.freeze({ title: "Not sent", text: "A run is in progress for this project. Your message was not stored." });
export const NOT_ACCEPTED_TEXT = "Waiting for the configuration to be accepted.";
export const EMPTY_TEXT = "No messages yet. Describe what you want done.";
export const AUTO_FLOW = "Let the planning agent route it";
export const AFTER_NONE = "None: it starts when it can";       // R-46: the first option of "After request"
export const AFTER_FORM_HINT = "The request waits until the one you pick is done or cancelled. Only requests still open are listed.";
export const FORM_HINT = "A flow plans the request from a predefined route. Without one, the planning agent routes it.";
const FINAL = new Set(["done", "cancelled"]);

/** The tab a route names: one of the four ids, `conversation` for none or for a word that is not a tab. */
export function tabOf(route) {
  const wanted = route && route.tab;
  return TABS.some(([id]) => id === wanted) ? wanted : "conversation";
}

/** How long to wait before the next read of the conversation: null while the document is hidden, and null when no job of this screen runs (the page reloads when the store changes). */
export function pollInterval({ jobRunning, hidden }) {
  if (hidden || !jobRunning) return null;
  return POLL_BUSY_MS;
}

/** The messages `have` plus the ones `got`, one per id, oldest first. */
export function mergeMessages(have, got) {
  const byId = new Map();
  for (const m of [...(have || []), ...(got || [])]) {
    if (m && Number.isInteger(m.id)) byId.set(m.id, m);
  }
  return [...byId.values()].sort((a, b) => a.id - b.id);
}

/** The id the next read asks above: the newest message's, or 0. */
export function lastId(messages) {
  return (messages || []).reduce((top, m) => (Number.isInteger(m.id) && m.id > top ? m.id : top), 0);
}

/** "4 h ago", "12 min ago" or "just now". */
export function ago(stamp, now) {
  return format.agoPhrase(format.age(stamp, now));
}

/** Who wrote a message, as the page words it. */
export function authorOf(role) {
  return role === "user" ? "You" : "Planning agent";
}

/** The meta line over a message: "You · 4 h ago"; a line stored while a run was in progress adds "· queued" until its reply arrives. */
export function metaOf(message, now) {
  const when = ago(message.created_at, now);
  const line = when ? `${authorOf(message.role)} · ${when}` : authorOf(message.role);
  return message.queued ? `${line} · ${QUEUED_WORD}` : line;
}

/** The name a message carries for a screen reader: "You, 4 hours ago"; "queued" when its reply is waiting for the run to end. */
export function nameOf(message, now) {
  const when = format.ageWords(message.created_at, now);
  const line = when ? `${authorOf(message.role)}, ${when === "just now" ? when : `${when} ago`}` : authorOf(message.role);
  return message.queued ? `${line}, ${QUEUED_WORD}` : line;
}

/** Whether any message of the log waits for the end of a run (its `queued` flag is on). */
export function hasQueued(messages) {
  return (messages || []).some((m) => m && m.queued === true);
}

/**
 * The id the next read of the conversation asks above: the newest message's, or, while a message is queued, the one before the oldest queued
 * message, so that the read brings it again without `queued` once its reply exists (a message already held is replaced by the newer copy).
 */
export function readAfter(messages) {
  const queued = (messages || []).filter((m) => m && m.queued === true && Number.isInteger(m.id)).map((m) => m.id);
  return queued.length ? Math.min(lastId(messages), Math.min(...queued) - 1) : lastId(messages);
}

/**
 * The task a run is in progress for, from a status body: {id, title, agent} of the oldest running task, or null. The composer says so before Send
 * (A-23). A router run holds a request, not a task, so it is not named here: `model.routingRequest` names it (A-51); the service queues the line all the same.
 */
export function runningTask(status) {
  for (const request of (Array.isArray(status && status.requests) ? status.requests : [])) {
    for (const task of (Array.isArray(request.tasks) ? request.tasks : [])) {
      if (task.state === "running") return { id: task.id, title: task.title || task.key || "", agent: task.agent || null };
    }
  }
  return null;
}

/**
 * Where each request's block goes: under the newest assistant message that names it (`byMessage`: message id -> request id),
 * or, for a request no message names (made from the form: OPEN-24), after the last message (`trailing`, oldest request first).
 * A request in a final state has no trailing block: nothing waits on it.
 */
export function placeBlocks(messages, requests) {
  const byMessage = new Map();
  const named = new Map();
  for (const m of messages || []) {
    if (m.role === "assistant" && Number.isInteger(m.task_id)) named.set(m.task_id, m.id);
  }
  for (const [request, message] of named) byMessage.set(message, request);
  const trailing = (requests || []).filter((r) => !named.has(r.id) && !FINAL.has(r.state)).map((r) => r.id).sort((a, b) => a - b);
  return { byMessage, trailing };
}

/**
 * The requests whose `task` body is read: every one that has an open decision in `pending` (by task_id: its card must be drawn
 * so that it can be answered), then the newest of the rest the conversation shows, up to MAX_BODIES in all (more when more than
 * MAX_BODIES have an open decision).
 */
export function wantedBodies(placed, requests, pending = []) {
  const known = new Set((requests || []).map((r) => r.id));
  const shown = [...new Set([...placed.byMessage.values(), ...placed.trailing])].filter((id) => known.has(id));
  const open = new Set((pending || []).map((p) => p.task_id));
  const must = shown.filter((id) => open.has(id)).sort((a, b) => b - a);
  const rest = shown.filter((id) => !open.has(id)).sort((a, b) => b - a);
  return [...must, ...rest.slice(0, Math.max(0, MAX_BODIES - must.length))];
}

/**
 * The requests whose `task` body the Inbox reads (P-6): the Inbox lists the decisions of every request of the project, so not only the requests the
 * conversation shows. The requests with a decision open come first (their cards must be drawn), then the others, newest first, a cancelled or done request
 * included (its resolved and cancelled lines are the Inbox's too); the whole is MAX_INBOX_BODIES at most, more when more requests than that have a decision
 * open. A request is read again only when its signature moves (signatureOf), never on every draw.
 */
export function inboxBodies(requests, pending = []) {
  const known = (requests || []).filter((r) => r && Number.isInteger(r.id)).map((r) => r.id);
  const open = new Set((pending || []).map((p) => p.task_id));
  const must = known.filter((id) => open.has(id)).sort((a, b) => b - a);
  const rest = known.filter((id) => !open.has(id)).sort((a, b) => b - a);
  return [...must, ...rest.slice(0, Math.max(0, MAX_INBOX_BODIES - must.length))];
}

/** A change signature of one request in a status body: the state, the task count and the open decisions' ids. */
export function signatureOf(request, pending) {
  const open = (pending || []).filter((p) => p.task_id === request.id).map((p) => p.id).join(",");
  return `${request.state}|${(request.tasks || []).length}|${open}`;
}

/** The decisions of the planning agent in a status body: those on a request (agent null) or of the planning agent. */
export function lobbyDecisions(status) {
  return (Array.isArray(status && status.pending) ? status.pending : []).filter((p) => !p.agent || p.agent === "planning");
}

/**
 * The Lobby's open decisions split between the Inbox's cards and the lines that point at the Conversation (OPEN-24). A plan on a
 * request that a message of the planning agent names has its card under that message, so the Inbox shows a line that points to it;
 * every other decision (a plan on a request made from the form, a question, an acceptance, a decision on the planning agent's own
 * task) has its card in the Inbox. Returns {cards, pointers}, each in the order of `status.pending`.
 */
export function inboxParts(status, messages) {
  const requests = Array.isArray(status && status.requests) ? status.requests : [];
  const named = new Set(placeBlocks(messages, requests).byMessage.values());
  const cards = [];
  const pointers = [];
  for (const item of lobbyDecisions(status)) {
    (item.kind === "plan" && named.has(item.task_id) ? pointers : cards).push(item);
  }
  return { cards, pointers };
}

/** True when a message of the planning agent names the request: its plan card is in the Conversation, not in the Inbox. */
export function isNamed(messages, requestId) {
  return (messages || []).some((m) => m.role === "assistant" && m.task_id === requestId);
}

/** The documents of the Lobby's Desk: every row of `artifacts` (C-2): the Lobby is the project's room; each row names its agent in a column. */
export function lobbyDocuments(rows) {
  return (Array.isArray(rows) ? rows : []).filter((d) => d && typeof d === "object");
}

/** The words of a request's state for its chip. */
export function stateWord(state) {
  if (typeof state !== "string" || !state) return "";
  return state.charAt(0).toUpperCase() + state.slice(1);
}

/** What the request line shows: {id, title, state, name, cancellable, routable}. `open` is the number of open decisions on it. */
export function requestLine(request, open) {
  const final = FINAL.has(request.state);
  return {
    id: request.id, title: request.title || `Request ${request.id}`, state: stateWord(request.state), final,
    name: `Request ${request.id}, ${request.title || ""}, ${request.state}`,
    tone: stateTone(request.state),     // C-23: the chip takes the state's colour (R-47)
    cancellable: !final,
    routable: request.state === "requested" && open === 0,
  };
}

/**
 * The words of a request line and the whole text behind them: {title, full}. `title` is the request's own title (the runtime computes it
 * when the person gives none), else the request's text; line breaks are spaces, so it is one line. `full` is the request's text (the
 * `task` answer's, else the row's), else the title: what the tooltip and the expanded line show.
 */
export function requestWords(request, body) {
  const one = (value) => String(value === undefined || value === null ? "" : value).replace(/\s+/g, " ").trim();
  const held = body && body.task && typeof body.task.text === "string" ? body.task.text : typeof request.text === "string" ? request.text : "";
  const title = one(request.title) || one(held);
  return { title, full: held.trim() || title };
}

/** The count line of the cancel dialog, from the request's tasks (`status`). */
export function cancelCount(request) {
  const tasks = Array.isArray(request && request.tasks) ? request.tasks : [];
  if (!tasks.length) return "No task has been created yet.";
  const untouched = new Set(["planned", "ready", "requested"]);
  const started = tasks.filter((t) => !untouched.has(t.state)).length;
  const n = `${tasks.length} task${tasks.length === 1 ? "" : "s"}`;
  return started === 0 ? `${n}, none started` : `${n}, ${started} started`;
}

/** The words of a decision that is no longer open: "Plan approved", "Question cancelled". */
export function resolvedWord(item) {
  const kind = format.kindWord(item.kind);
  if (item.status === "cancelled") return `${kind} cancelled`;
  return item.resolution ? `${kind} ${item.resolution}` : `${kind} resolved`;
}

/**
 * The options of "After request" (R-46): the first is `None: it starts when it can`, then one option for every request that is not final, by number from the
 * lowest: `#<n> <title> · <state>`; a request that waits for its route says `Waiting for its route`, as the page draws it. A request that is done or cancelled
 * is not offered, so the number cannot be wrong. The value of an option is the request's number as text.
 */
export function afterOptions(requests) {
  const open = (Array.isArray(requests) ? requests : []).filter((r) => r && Number.isInteger(r.id) && !FINAL.has(r.state)).sort((a, b) => a.id - b.id);
  return [{ value: "", label: AFTER_NONE }, ...open.map((r) => {
    const title = requestWords(r, null).title || `Request ${r.id}`;
    return { value: String(r.id), label: `#${r.id} ${title} · ${r.state === "requested" ? "Waiting for its route" : stateWord(r.state)}` };
  })];
}

/**
 * The commands the list shows for what is typed (R-45): rows are `{command, arguments, help}` as the service gave them. The list is open while the
 * field holds one word that starts with `/` (no space or line break yet): the rows whose command starts with it, in the service's order. `[]` for any other text.
 */
export function commandMatches(rows, typed) {
  if (typeof typed !== "string" || !/^\/\S*$/.test(typed)) return [];
  const word = typed.toLowerCase();
  return (Array.isArray(rows) ? rows : []).filter((r) => r && typeof r.command === "string" && r.command.toLowerCase().startsWith(word));
}

/** What choosing a command writes in the field: the command, and a space after it when it takes arguments. */
export function commandFill(row) {
  return `${row.command}${row.arguments ? " " : ""}`;
}

/** The options of the Flow select: the first is the planning agent's own route, then one per flow, labelled by its title. */
export function flowOptions(flows) {
  const listed = (Array.isArray(flows) ? flows : []).filter((f) => f && typeof f.flow === "string" && !f.error);
  return [{ value: "", label: AUTO_FLOW }, ...listed.map((f) => ({ value: f.flow, label: typeof f.title === "string" && f.title ? f.title : f.flow }))];
}

/**
 * The notice a `say` that did not run shows, {title, text}. `phase` is "post" when the service refused the call itself (nothing
 * was stored: the 409 busy answer has the drawing's words, any other refusal its own message) and "job" when the job failed (the
 * job's own message, OPEN-23).
 */
export function noticeFor(error, phase = "post") {
  if (error && error.status === 409 && error.word === "busy") return BUSY_NOTICE;
  const text = (error && typeof error.message === "string" && error.message) || "The planning agent's turn failed.";
  return { title: phase === "job" ? "The turn failed" : "Not sent", text };
}

/** The notice after a request was made but not routed (the 409 busy answer of `route`, or the router's run failing). */
export function notRoutedNotice(id, reason) {
  return { title: "Not routed yet", text: `Request #${id} was created. ${reason} Use "Route it" on its request line.` };
}

const DOT = { working: "theme", waiting: "warn", ready: "theme", idle: "muted", off: "border" };

/**
 * What the Lobby's room needs, as the plain model of the room scene (the shape the Floor's room builder reads: `ready`, `state`,
 * `window`, `decisions`, `drawers`, `sheets`, `tips`, `board`) with `door: true` for the door to the Control room. The planning agent
 * works while a turn or a route of this screen runs, waits when a decision of the Lobby waits, is off when the project is not
 * accepted and is idle otherwise. `documents` are the Desk's rows (see lobbyDocuments), as the Floor takes them: the sheets and the cabinet's
 * drawers; null while they are unread (the world keeps what the table shows: an empty cabinet at first).
 */
export function roomModel({ working, decisions, hasMessages, accepted, request, ready = true, documents = null, queued = false }) {
  let state = "idle";
  if (!accepted) state = "off";
  else if (working) state = "working";
  else if (decisions > 0) state = "waiting";
  else if (queued) state = "ready";   // M-24: a task of the planning agent is queued and not held
  const words = { working: "working", waiting: "waiting for you", ready: "queued · starts when the current run ends", idle: "idle", off: "off" }[state];
  const docs = Array.isArray(documents) ? documents : null;
  const board = request
    ? { title: request.title || `Request ${request.id}`, lines: [`request #${request.id} · ${request.state}`], dot: DOT[state] }
    : { title: accepted ? "No request is open" : NOT_ACCEPTED_TEXT, lines: [], dot: DOT[state] };
  return {
    kind: "room", ready, door: true, state, window: windowState(state === "working" || state === "waiting" || state === "ready"), decisions, drawers: docs ? drawersOf(docs.length) : null,
    sheets: docs ? docs.slice(0, 6).map((d) => ({ path: d.path, tip: d.path })) : null, documents: docs ? docs.length : null, empty: !hasMessages,
    tips: {
      agent: `Planning agent · ${words}`, desk: request ? `Current task · ${request.title || `request #${request.id}`}` : "Current task · none yet",
      tray: `Inbox · ${decisions} waiting`,
      cabinet: docs ? `${docs.length} document${docs.length === 1 ? "" : "s"} · open the Desk tab` : "Documents · open the Desk tab", board: board.lines[0] || board.title,
      door: "Control room · skills, costs, connections",
    },
    board,
  };
}

/** The canvas label of the Lobby, built from the data. */
export function canvasLabel(projectName, room) {
  const n = room.decisions;
  return `Lobby of ${projectName || "the project"}, planning agent ${room.state}, ${n} decision${n === 1 ? "" : "s"}, door to the Control room`;
}
