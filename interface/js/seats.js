// Which owl sits where on a floor: pure, no page, no library. A floor draws one workstation for each task that holds a slot of its agent, filling the L's
// seats in order; when no task holds one the floor has its one owl at seat 0, asleep or awake by the floor's state. The runtime says who holds a slot (`holds_slot`); the page
// decides nothing about slots and writes no cap: the only number here is how many places the room has.

import { SEAT_COUNT } from "./scene/seats-layout.js";

const POSE_OF_TASK = { running: "working", waiting: "waiting", ready: "ready" };

/** The pose of a floor's one owl when no task holds a slot: by the floor's own state (the same words `owlPose` of scene/building.js uses). */
const POSE_OF_FLOOR = { working: "working", waiting: "waiting", ready: "ready" };

/**
 * The seats of a floor: [{seat: 0..3, pose, taskId}]. `tasks` is the floor's `holders`: every task of the agent, of every request, as {id, state, holds_slot}; a task whose
 * `holds_slot` is not true sits nowhere. `state` and `accepted` are the floor row's: an agent that is off, or a project not accepted, has an empty room.
 * Holders sit by id, the first in seat 0; there can briefly be more holders than places (an answered task back from a derived wait): then the typing ones are kept first, so no
 * typing owl is dropped, and the places go to the kept ones by id. With no holder, one owl at seat 0, taskId null.
 */
export function seatsOf(tasks, { state, accepted } = {}) {
  if (accepted === false || state === "off") return [];
  const holders = (Array.isArray(tasks) ? tasks : []).filter((t) => t && t.holds_slot === true).sort((a, b) => a.id - b.id);
  if (!holders.length) return [{ seat: 0, pose: POSE_OF_FLOOR[state] || "idle", taskId: null }];
  const kept = holders.length > SEAT_COUNT
    ? [...holders.filter((t) => t.state === "running"), ...holders.filter((t) => t.state !== "running")].slice(0, SEAT_COUNT).sort((a, b) => a.id - b.id)
    : holders;
  return kept.map((t, seat) => ({ seat, pose: POSE_OF_TASK[t.state] || "ready", taskId: t.id }));
}
