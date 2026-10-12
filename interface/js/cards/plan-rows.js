// What the plan card shows, worked out from the decision's `payload` (pure functions: no document, no network). The table
// comes from `payload.tasks`, the limits line from `payload.limits` and `payload.estimate`, the hash is `payload.plan_sha256`
// whole; nothing is copied from the text `body`. A value the operation did not store is "-", never a guess.

const DASH = "-";

/** A plan's payload as an object, or an empty one. */
export function payloadOf(item) {
  return item && item.payload && typeof item.payload === "object" ? item.payload : {};
}

/** The positions (from 1) of the keys a task waits for, joined by ", ", or "-". */
export function afterOf(task, keys) {
  const waits = Array.isArray(task.depends_on) ? task.depends_on : [];
  const positions = waits.map((key) => keys.get(key)).filter((n) => n !== undefined);
  return positions.length ? positions.join(", ") : DASH;
}

/** "no", "yes" or "yes (mandatory)". */
export function milestoneWord(task) {
  if (task.mandatory_milestone) return "yes (mandatory)";
  return task.milestone ? "yes" : "no";
}

/** The rows of the tasks table: #, Task, Skill, Agent, After, Milestone, Web. */
export function taskRows(item) {
  const tasks = Array.isArray(payloadOf(item).tasks) ? payloadOf(item).tasks : [];
  const keys = new Map(tasks.map((t, i) => [t.key, i + 1]));
  return tasks.map((t, i) => ({
    n: String(i + 1),
    task: typeof t.title === "string" && t.title ? t.title : String(t.key || DASH),
    skill: typeof t.skill === "string" && t.skill ? t.skill : DASH,
    agent: typeof t.agent === "string" && t.agent ? t.agent : DASH,
    after: afterOf(t, keys),
    milestone: milestoneWord(t),
    web: t.web ? "yes" : "no",
  }));
}

export const COLUMNS = Object.freeze(["#", "Task", "Skill", "Agent", "After", "Milestone", "Web"]);

/** "One task at a time; each run at most 1800 s, retried at most 2 times. At least 4 runs." (each part only when stored). */
export function limitsLine(item) {
  const payload = payloadOf(item);
  const limits = payload.limits && typeof payload.limits === "object" ? payload.limits : {};
  const parts = [];
  const run = [];
  if (Number.isFinite(limits.timeout_seconds)) run.push(`each run at most ${limits.timeout_seconds} s`);
  if (Number.isFinite(limits.retries)) run.push(`retried at most ${limits.retries} time${limits.retries === 1 ? "" : "s"}`);
  const first = [limits.one_task_at_a_time ? "One task at a time" : "", run.join(", ")].filter(Boolean).join("; ");
  if (first) parts.push(`${first}.`);
  const estimate = payload.estimate && typeof payload.estimate === "object" ? payload.estimate : {};
  if (Number.isFinite(estimate.runs_at_least)) parts.push(`At least ${estimate.runs_at_least} run${estimate.runs_at_least === 1 ? "" : "s"}.`);
  return parts.join(" ");
}

/** The hash shown and sent: `payload.plan_sha256`, or "" when the decision carries none (the card then offers no approval). */
export function planHash(item) {
  const hash = payloadOf(item).plan_sha256;
  return typeof hash === "string" && /^[0-9a-f]{64}$/.test(hash) ? hash : "";
}

/** The plan's text for the disclosure: the stored `body`, whole. */
export function planText(item) {
  return item && typeof item.body === "string" ? item.body : "";
}

export const BUSY_TEXT = "A model run is already going for this project. Nothing was started; try again when it ends.";

/** The sentence a failed call shows above the control that sent it: the service's own message, with the two words the cards give their own text. */
export function failureText(error) {
  if (error && error.status === 409 && error.word === "busy") return BUSY_TEXT;
  if (error && error.status === 404) return "That item is not there any more.";
  return error && typeof error.message === "string" && error.message ? error.message : "The request failed.";
}

/** One task as the stacked block of a phone: line 1 "1  Build the page", line 2 the skill (and the agent), line 3 "After 1 · Milestone yes · Web no". */
export function stackedRow(row) {
  return {
    head: `${row.n}  ${row.task}`,
    skill: row.skill,
    agent: row.agent === DASH ? "" : row.agent,
    tail: `After ${row.after} · Milestone ${row.milestone} · Web ${row.web}`,
  };
}
