// What the Lobby sends, as functions that take the client (`api`, the module of js/api.js) so a test can stand in for it. The page
// builds no prompt, summary or plan: a turn is the text as typed; a request is the text, the optional title and, in a second call,
// the chosen flow.

import { toBase64 } from "../floor/hand-file.js";
import { JOB_EVERY_MS } from "./lobby-model.js";

/**
 * Create a request from the form: `request` with the text and the title when one was typed and NEVER a flow (a request that
 * names a flow readies its tasks with no approval of the plan: DIFF-57), then `route` with the chosen flow, or with none when
 * the first option was chosen (the planning agent then routes it). `route` is a job.
 * `form.after` is the number of the request this one runs after (A-29), sent as `after`; see afterNumber.
 * Returns {request, started} when the route started (started is the job), or {request, error} when `route` was refused (a 409
 * busy answer: the request exists and waits for its route). `request` itself failing throws. With `route: false` (the page may not route,
 * js/permissions.js) the second call is not made: {request, unrouted: true}, and the request waits for its route.
 */
export async function createRequest(api, project, form, { signal, route = true } = {}) {
  const text = typeof form.text === "string" ? form.text : "";
  if (!text.trim()) return { request: null, empty: true };
  const title = typeof form.title === "string" && form.title.trim() ? form.title.trim() : undefined;
  const after = afterNumber(form.after).value;
  const model = typeof form.model === "string" && form.model ? form.model : undefined;
  const made = await api.request(project, text, { title, after, model, signal });
  if (!route) return { request: made.request, unrouted: true };
  // A flow with a file parameter (P6a): each file chosen is handed over for the request first (stage-file), and the parameter is the file's name, so the
  // plan that route builds carries the hash of exactly that file. A refusal of the hand-over leaves the request waiting for its route, like a busy router.
  const params = Array.isArray(form.params) ? [...form.params] : [];
  for (const { param, file } of Array.isArray(form.files) ? form.files : []) {
    try {
      await api.stageFile(project, made.request, file.name, toBase64(new Uint8Array(await file.arrayBuffer())), { signal });
    } catch (e) {
      if (e && e.name === "ApiError") return { request: made.request, error: e };
      throw e;
    }
    params.push(`${param}=${file.name}`);
  }
  const out = await routeRequest(api, project, made.request, form.flow, { params, signal });
  return params.length ? { ...out, params } : out;
}

/** The "After request #" field: {value} (a request number, or undefined when the field is empty) or {invalid: true}. */
export function afterNumber(raw) {
  const text = typeof raw === "string" ? raw.trim().replace(/^#/, "") : typeof raw === "number" ? String(raw) : "";
  if (!text) return { value: undefined };
  return /^[0-9]{1,9}$/.test(text) && Number(text) > 0 ? { value: Number(text) } : { invalid: true };
}

/** Route a request that waits for its route, with the chosen flow when there is one and the flow's parameters (a list of "name=value"). */
export async function routeRequest(api, project, id, flow, { params, signal } = {}) {
  try {
    const started = await api.route(project, id, { flow: flow || undefined, params: flow ? params : undefined, signal });
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
