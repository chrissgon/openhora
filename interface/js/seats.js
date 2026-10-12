// Which owl sits where on a floor: pure, no page, no library. A floor draws one workstation for each place of its agent (`max_parallel`), filling the L's
// seats in order with the tasks that hold a slot; a free place has its owl asleep. The runtime says who holds a slot (`holds_slot`); the page
// decides nothing about slots and writes no cap: the only number here is how many places the room has.

import { SEAT_COUNT } from "./scene/seats-layout.js";

const POSE_OF_TASK = { running: "working", waiting: "waiting", ready: "ready" };

/** The pose of a floor's one owl when no task holds a slot: by the floor's own state (the same words `owlPose` of scene/building.js uses). */
const POSE_OF_FLOOR = { working: "working", waiting: "waiting", ready: "ready" };

/**
 * The seats of a floor: [{seat: 0..3, pose, taskId}]. `tasks` is the floor's `holders`: every task of the agent, of every request, as {id, state, holds_slot}; a task whose
 * `holds_slot` is not true sits nowhere. `state`, `accepted` and `maxParallel` are the floor row's: an agent that is off, or a project not accepted, keeps its desks with no owl (`pose` null).
 * `maxParallel` (the agent's slots) is how many places the floor shows: the holders sit by id, the first in seat 0; there can briefly be more holders than places (an answered task back from a derived wait): then the typing ones are kept first, so no
 * typing owl is dropped, and the places go to the kept ones by id. Every place left after the holders is a free slot: its owl sleeps (`idle`). With no holder, seat 0 has the pose of the floor's state.
 */
export function seatsOf(tasks, { state, accepted, maxParallel } = {}) {
  const count = Math.min(Math.max(Number.isInteger(maxParallel) ? maxParallel : 1, 1), SEAT_COUNT);
  // a floor that is off (disabled, stopped) or of a project not accepted keeps its desks and has no owl
  if (accepted === false || state === "off") return Array.from({ length: count }, (_, seat) => ({ seat, pose: null, taskId: null }));
  const holders = (Array.isArray(tasks) ? tasks : []).filter((t) => t && t.holds_slot === true).sort((a, b) => a.id - b.id);
  const kept = holders.length > SEAT_COUNT
    ? [...holders.filter((t) => t.state === "running"), ...holders.filter((t) => t.state !== "running")].slice(0, SEAT_COUNT).sort((a, b) => a.id - b.id)
    : holders;
  const seats = kept.map((t, seat) => ({ seat, pose: POSE_OF_TASK[t.state] || "ready", taskId: t.id }));
  // with no holder, seat 0 keeps the pose of the floor's state (the Lobby routing, a question waiting, a queued floor)
  if (!seats.length) seats.push({ seat: 0, pose: POSE_OF_FLOOR[state] || "idle", taskId: null });
  // every other place of the floor is free: its owl sleeps in its chair
  for (let seat = seats.length; seat < count; seat += 1) seats.push({ seat, pose: "idle", taskId: null });
  return seats;
}
