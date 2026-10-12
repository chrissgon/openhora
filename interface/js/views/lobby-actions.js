// What the Lobby sends, as functions that take the client (`api`, the module of js/api.js) so a test can stand in for it. The page
// builds no prompt, summary or plan: a turn is the text as typed; a request is the text, the optional title and, in a second call,
// the chosen flow.

import { JOB_EVERY_MS } from "./lobby-model.js";

/**
 * Create a request from the form: `request` with the text and the title when one was typed and NEVER a flow (a request that
 * names a flow readies its tasks with no approval of the plan: DIFF-57), then `route` with the chosen flow, or with none when
 * the first option was chosen (the planning agent then routes it). `route` is a job.
 * `form.after` is the number of the request this one runs after (A-29), sent as `after`; see afterNumber.
 * Returns {request, started} when the route started (started is the job), or {request, error} when `route` was refused (a 409
 * busy answer: the request exists and waits for its route). `request` itself failing throws.
 */
export async function createRequest(api, project, form, { signal } = {}) {
  const text = typeof form.text === "string" ? form.text : "";
  if (!text.trim()) return { request: null, empty: true };
  const title = typeof form.title === "string" && form.title.trim() ? form.title.trim() : undefined;
  const after = afterNumber(form.after).value;
  const made = await api.request(project, text, { title, after, signal });
  return routeRequest(api, project, made.request, form.flow, { signal });
}

/** The "After request #" field: {value} (a request number, or undefined when the field is empty) or {invalid: true}. */
export function afterNumber(raw) {
  const text = typeof raw === "string" ? raw.trim().replace(/^#/, "") : typeof raw === "number" ? String(raw) : "";
  if (!text) return { value: undefined };
  return /^[0-9]{1,9}$/.test(text) && Number(text) > 0 ? { value: Number(text) } : { invalid: true };
}

/** Route a request that waits for its route, with the chosen flow when there is one. */
export async function routeRequest(api, project, id, flow, { signal } = {}) {
  try {
    const started = await api.route(project, id, { flow: flow || undefined, signal });
    return { request: id, started };
  } catch (e) {
    if (e && e.name === "ApiError") return { request: id, error: e };
    throw e;
  }
}

/** Wait for a job; returns its last answer (state `done` or `failed`). */
export function waitFor(api, job, { signal, onUpdate } = {}) {
  return api.pollJob(job.job, JOB_EVERY_MS, { signal, onUpdate });
}

/** Send one turn: `say` with the text exactly as typed. Returns the job; an ApiError (409 busy) is thrown. */
export function sendTurn(api, project, text, { signal } = {}) {
  return api.say(project, text, { signal });
}

/** Whether a line is worth sending: not empty and not only white space. */
export function worthSending(text) {
  return typeof text === "string" && text.trim().length > 0;
}
