// What each owl of a floor says and opens (SPEC-PAR-7 section 12, PAR-7e): every owl is selected on its own. Pure: no three.js and no document.
//
// An owl of a task that holds a slot names the task and its state and opens it (the Tasks tab with the task open, or its decision in the Inbox when it waits for the person and has
// one); an owl of a free place is asleep and opens the Agent tab; the one owl the floor's own state draws (no task holds a slot: the Lobby routing, a question waiting, a queued
// floor) keeps the floor's tooltip and click, which are its ids `agent` and `tray` as before. The world gives each owl a pick target of its own with the id and the words here, the
// views open the destination, and the owls' twin list (floor/owl-list.js) shows the same words.

import { QUEUED_NOTE } from "./floor-model.js";
import { agentTip } from "./scene/room-words.js";

export const FREE_TIP = "Free slot · asleep";

/** The id of the pick target of the owl at `seat` (the owl the floor's state draws has `agent` or `tray` instead). */
export const owlId = (seat) => `owl:${seat}`;

const WORDS = { working: "working", waiting: "waiting for you", ready: `queued · ${QUEUED_NOTE}` };

/**
 * The owls of a floor in seat order, each {seat, id, tip, kind: "task" | "free" | "floor", taskId, route: {tab, id}}, from the floor's `seats` ([{seat, pose, taskId}]; a seat with no
 * pose has no owl and no target), the agent's `tasks` (floor-model.agentTasks) and open `decisions` (agentDecisions), `floorTip` (the floor's tooltip for its agent, the model's words) and
 * `asks` (the agent waits and has a decision open: a click on the floor's owl goes to the Inbox). `route` says where a click goes: `tab` is the floor's tab and `id` the task (Tasks) or the
 * decision (Inbox) to open there, absent for the others.
 */
export function owlTargets({ seats, tasks = [], decisions = [], floorTip = "", asks = false }) {
  const out = [];
  for (const s of Array.isArray(seats) ? seats : []) {
    if (!s || !s.pose) continue;
    if (s.taskId !== null && s.taskId !== undefined) {
      const task = tasks.find((t) => t.id === s.taskId) || null;
      const decision = s.pose === "waiting" ? decisions.find((d) => d.task_id === s.taskId) || null : null;
      const name = task ? task.title || task.key || "" : "";
      const words = `${WORDS[s.pose] || ""}${decision ? " · open the Inbox" : ""}`;
      out.push({
        seat: s.seat, id: owlId(s.seat), kind: "task", taskId: s.taskId,
        tip: `#${s.taskId}${name ? ` ${name}` : ""}${words ? ` · ${words}` : ""}`,
        route: decision ? { tab: "inbox", id: decision.id } : { tab: "tasks", id: s.taskId },
      });
    } else if (s.pose === "idle") {
      out.push({ seat: s.seat, id: owlId(s.seat), kind: "free", taskId: null, tip: FREE_TIP, route: { tab: "agent" } });
    } else {
      out.push({ seat: s.seat, id: asks ? "tray" : "agent", kind: "floor", taskId: null, tip: agentTip(floorTip, asks), route: { tab: asks ? "inbox" : "agent" } });
    }
  }
  return out;
}

/**
 * Open the destination of the owl whose pick id is `id` among `targets`: calls `go(tab, id)` (the view builds the hash with the router) and returns true; false when no owl has that id,
 * so a click on anything else falls through to the view's other objects.
 */
export function openOwl(targets, id, go) {
  const target = (Array.isArray(targets) ? targets : []).find((t) => t.id === id && t.kind !== "floor");
  if (!target) return false;
  go(target.route.tab, target.route.id);
  return true;
}
