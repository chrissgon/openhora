// What a task waits for (A-29), worked out from the `waiting_for` of a task row: [{task_id, request_id, reason}] (empty when none; `task_id` is
// the awaited task, null for an `after` wait, whose `request_id` is the awaited request). Pure functions with no document and no network:
// every word is the runtime's `reason`, or "#n" built from the ids it gave. A task that waits keeps the state word `planned`.

/** The waits of a task: only the entries that are objects with a text reason. */
export function waitsOf(task) {
  const list = task && Array.isArray(task.waiting_for) ? task.waiting_for : [];
  return list.filter((w) => w && typeof w === "object" && typeof w.reason === "string" && w.reason);
}

/** Whether a wait is the person's `after` override (it awaits a request) and not a derived one (it awaits a task). */
export function isAfter(wait) {
  return wait.task_id === null || wait.task_id === undefined;
}

/** "#10" for a task, "request #3" for a request. */
function awaited(wait) {
  if (!isAfter(wait)) return `#${wait.task_id}`;
  return Number.isInteger(wait.request_id) ? `request #${wait.request_id}` : "a request";
}

/** The short words of a task's waits: "waiting for #10, request #3"; "" when it waits for nothing. */
export function waitingLabel(task) {
  const waits = waitsOf(task);
  return waits.length ? `waiting for ${[...new Set(waits.map(awaited))].join(", ")}` : "";
}

/**
 * One line per wait, with the runtime's reason: "waiting for #10: docs/brand/identity.md, written by task #10". The person's own `after` reads
 * "waiting for request #7" once: its reason ("after request #7") says no more than that.
 */
export function waitLines(task) {
  return waitsOf(task).map((w) => (isAfter(w) ? `waiting for ${awaited(w)}` : `waiting for ${awaited(w)}: ${w.reason}`));
}

/** Whether the person can say "Go ahead" on the task (a derived wait is open) and whether they can drop its `after`. */
export function waitKinds(task) {
  const waits = waitsOf(task);
  return { goAhead: waits.some((w) => !isAfter(w)), dropAfter: waits.some(isAfter) };
}
