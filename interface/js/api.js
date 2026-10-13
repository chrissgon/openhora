// The client of the local service (runtime/service.py): one function per route of its ROUTES table, named after the
// operation. Each sends the token as "Authorization: Bearer" (one exception, tokenFile: the read of the token file's path, before the page
// has a token, sends none), a POST sends "Content-Type: application/json", and
// only a route that takes a query (progress, conversation, costs, artifact, artifact/raw) is sent one. An error body {error, message} becomes an ApiError with
// the status and the word. A route whose operation calls a model or a platform answers 202 with a job: the function
// returns that job and pollJob(job.job, every) asks for it again until it is done or failed. The token is read from
// token.js for each request and appears nowhere else here. One route answers bytes (the raw artifact): `artifactRaw` returns a Blob,
// through the same `send`, so the token still travels only as the bearer header. `send` is the one place a request leaves the client, and it
// hands the request to transport.js (the page's single network call).

import { getToken } from "./token.js";
import { transport, transportUpload } from "./transport.js";

const PREFIX = "/api/v1";
const TOKEN_FILE = "/token-file";   // the one path outside PREFIX: it needs no token, so the page can show where the token file is before it has one

// The words the service gives an error (runtime/service.py WORDS), by status, for a body that carries none.
const WORD_OF_STATUS = {
  400: "usage", 401: "token", 403: "host", 404: "not_found", 405: "method", 409: "refused", 411: "length",
  412: "not_configured", 413: "too_large", 415: "content_type", 500: "internal", 503: "stopping", 507: "no_space",
};

/** An answer the service refused, or a request that did not get one (status 0, word "network"). */
export class ApiError extends Error {
  constructor(status, word, message, next = null) {
    super(message || word);
    this.name = "ApiError";
    this.status = status;
    this.word = word;
    this.next = next;      // the terminal command that gets past the refusal, as the service gave it (the 412: accept-config), or null
  }

  /** 409 busy: a job that calls a model is already running for this project. */
  get busy() { return this.status === 409 && this.word === "busy"; }

  /** 409 refused: the operation refused (a rule of the work, not a malformed request). */
  get refused() { return this.status === 409 && this.word === "refused"; }

  /** 412: the project's configuration is not accepted yet (the terminal's accept-config does that). */
  get notConfigured() { return this.status === 412; }

  /** 401: the token is missing or is not the service's current one. */
  get unauthorized() { return this.status === 401; }

  /** 400: the request is malformed. */
  get usage() { return this.status === 400; }
}

let authFailure = null;

/** Register the one function called when the service answers 401 (the page then asks for the token again). */
export function onAuthFailure(fn) {
  authFailure = fn;
}

let writeHook = null;

/**
 * Register the one function called after the service answered a POST, whatever it answered ({method, path, status}): a
 * write the page sent may have changed what every screen shows, so the page reloads at once. It is not called for a request
 * that got no answer, nor for a GET.
 */
export function onWrite(fn) {
  writeHook = fn;
}

const enc = (part) => encodeURIComponent(String(part));

async function send(method, path, options = {}) {
  const open = options.open === true;   // the unauthenticated read below: no bearer header, and no token needed
  const token = getToken();
  if (!token && !open) {
    if (authFailure) authFailure();
    throw new ApiError(401, "token", "There is no token yet.");
  }
  let url = (open ? "" : PREFIX) + path;
  if (options.query) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(options.query)) {
      if (value !== undefined && value !== null) query.append(key, String(value));
    }
    const text = query.toString();
    if (text) url += "?" + text;
  }
  const headers = { Accept: options.raw ? "image/*" : "application/json" };
  if (!open) headers.Authorization = `Bearer ${token}`;
  const init = {
    method, headers, credentials: "omit", cache: "no-store", redirect: "error", mode: "same-origin",
    // "same-origin", never "no-referrer": under no-referrer a browser that follows the Fetch spec (Safari, so a phone) serialises the
    // Origin of a POST as `null`, which the service refuses. Same-origin keeps the real Origin and sends a referrer to this service alone.
    referrerPolicy: "same-origin", signal: options.signal,
  };
  if (method === "POST" && options.blob) {
    // the media route (rule 5's exception): the file's own bytes, never base64, with a progress report; the Content-Length is the browser's
    headers["Content-Type"] = "application/octet-stream";
    Object.assign(headers, options.headers || {});
    init.body = options.blob;
  } else if (method === "POST") {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body || {});
  }
  const move = options.progress ? (u, i) => transportUpload(u, i, options.progress) : (u, i) => transport(u, i);
  let response;
  try {
    response = await move(url, init);
  } catch (e) {
    if (e && e.name === "AbortError") throw e;
    // a large upload the service refused before it read the body may be closed under the browser before the answer arrives
    if (options.blob) throw new ApiError(0, "network", "The upload was refused or the connection closed before the service answered.");
    throw new ApiError(0, "network", "The service could not be reached. Is it still running?");
  }
  // A route marked `raw` answers bytes: read them as a Blob on success; a refusal is JSON as everywhere else.
  if (options.raw && response.ok) {
    try {
      return await response.blob();
    } catch (e) {
      throw new ApiError(response.status, "internal", "The service answered with bytes this page could not read.");
    }
  }
  let data = null;
  try {
    data = await response.json();
  } catch (e) {
    data = null;
  }
  if (method === "POST" && writeHook) {
    try {
      writeHook({ method, path, status: response.status });
    } catch (e) {
      // the hook is the page's; a failure there never changes what the caller gets
    }
  }
  if (!response.ok) {
    const word = (data && typeof data.error === "string" && data.error) || WORD_OF_STATUS[response.status] || "internal";
    const message = (data && typeof data.message === "string" && data.message) || word;
    const next = data && typeof data.next === "string" && data.next ? data.next : null;
    const failure = new ApiError(response.status, word, message, next);
    if (failure.unauthorized && authFailure && !open) authFailure();
    throw failure;
  }
  if (data === null || typeof data !== "object") throw new ApiError(response.status, "internal", "The service answered with something that is not JSON.");
  return data;
}

/**
 * GET /token-file, before the page holds a token: {token_file, commands: {macos, linux, powershell}}, the absolute path of the token
 * file and the commands, built by the service, that read it; both null when the path has no safe command. It is sent with no bearer
 * header (even when a token is held) and a 404 means an older service. It never carries the token.
 */
export function tokenFile(options = {}) {
  return send("GET", TOKEN_FILE, { signal: options.signal, open: true });
}

// --- the routes, in the order of ROUTES --------------------------------------------------------------------------
// A function marked (job) answers 202: it returns the job {job, op, project, state, result, error, started_at,
// ended_at}; hand job.job to pollJob. The other functions return what the operation returned.

/** GET /projects: {projects: [{id, name, config: {sha256, accepted}, message?, open_pending?, running_task?, running_tasks?, routing_request?}]}; `running_tasks` are the numbers of the tasks that run, `running_task` the lowest. */
export function projects(options) {
  return send("GET", "/projects", options);
}

/** GET /projects/{p}/version: {version, changed_at}, a number that grows on every write to the project's store. */
export function version(p, options) {
  return send("GET", `/projects/${enc(p)}/version`, options);
}

/** GET /versions: {versions: {<project id>: {version, changed_at} | {error}}}, the same for every project in one request. */
export function versions(options) {
  return send("GET", "/versions", options);
}

/** GET /projects/{p}/status: the requests with their tasks, the open decisions, the documents. */
export function status(p, options) {
  return send("GET", `/projects/${enc(p)}/status`, options);
}

/** GET /projects/{p}/pending: the open decisions, each with the actions it takes. */
export function pending(p, options) {
  return send("GET", `/projects/${enc(p)}/pending`, options);
}

/** GET /projects/{p}/pending/{id}: one decision with its body and payload. */
export function pendingItem(p, id, options) {
  return send("GET", `/projects/${enc(p)}/pending/${enc(id)}`, options);
}

/** POST /projects/{p}/pending/{id}/answer: {text, with_comments?}. */
export function answer(p, id, text, { withComments, signal } = {}) {
  return send("POST", `/projects/${enc(p)}/pending/${enc(id)}/answer`, { body: { text, with_comments: withComments }, signal });
}

/** POST /projects/{p}/pending/{id}/release (job). */
export function release(p, id, options) {
  return send("POST", `/projects/${enc(p)}/pending/${enc(id)}/release`, options);
}

/**
 * POST /projects/{p}/pending/{id}/approve (job): {sha256, go_ahead?}, the hash of the content the page showed and, for a plan,
 * the keys of the tasks the person told to go ahead (a JSON list: their derived waits are dropped). `goAhead` left out or empty sends no list.
 */
export function approve(p, id, sha256, options = {}) {
  const goAhead = Array.isArray(options.goAhead) && options.goAhead.length ? options.goAhead : undefined;
  return send("POST", `/projects/${enc(p)}/pending/${enc(id)}/approve`, { body: { sha256, go_ahead: goAhead }, signal: options.signal });
}

/** POST /projects/{p}/pending/{id}/reject: {note?}. */
export function reject(p, id, note, options = {}) {
  return send("POST", `/projects/${enc(p)}/pending/${enc(id)}/reject`, { body: { note }, signal: options.signal });
}

/** GET /projects/{p}/flows: the flow files of the checkout. */
export function flows(p, options) {
  return send("GET", `/projects/${enc(p)}/flows`, options);
}

/** POST /projects/{p}/requests: {text, flow?, title?, after?}; `after` is the number of the request this one runs after. */
export function request(p, text, { flow, title, after, signal } = {}) {
  return send("POST", `/projects/${enc(p)}/requests`, { body: { text, flow, title, after }, signal });
}

/** POST /projects/{p}/requests/{id}/route (job): {flow?}. */
export function route(p, id, { flow, signal } = {}) {
  return send("POST", `/projects/${enc(p)}/requests/${enc(id)}/route`, { body: { flow }, signal });
}

/** POST /projects/{p}/requests/{id}/cancel. */
export function cancel(p, id, options) {
  return send("POST", `/projects/${enc(p)}/requests/${enc(id)}/cancel`, options);
}

/** GET /projects/{p}/tasks/{id}: the task, its runs and its decisions. */
export function task(p, id, options) {
  return send("GET", `/projects/${enc(p)}/tasks/${enc(id)}`, options);
}

/** POST /projects/{p}/tasks/{id}/retry. */
export function retry(p, id, options) {
  return send("POST", `/projects/${enc(p)}/tasks/${enc(id)}/retry`, options);
}

/** POST /projects/{p}/tasks/{id}/go-ahead: {drop_after?}; ends the derived waits of a task already created (with `dropAfter`, its `after` wait instead). */
export function goAhead(p, id, { dropAfter, signal } = {}) {
  return send("POST", `/projects/${enc(p)}/tasks/${enc(id)}/go-ahead`, { body: { drop_after: dropAfter ? true : undefined }, signal });
}

/** POST /projects/{p}/tasks/{id}/files: hand a file to a task, {name, content_base64}. */
export function handOver(p, id, name, contentBase64, options = {}) {
  return send("POST", `/projects/${enc(p)}/tasks/${enc(id)}/files`, { body: { name, content_base64: contentBase64 }, signal: options.signal });
}

/**
 * POST /projects/{p}/media: stream a recording (or, with `slot`, the file of an asset slot of `recording`) to the media store. The body is the
 * file's own bytes (application/octet-stream), so it is never held whole in memory; `onProgress(sent, total)` reports the upload. The service
 * answers on the loopback socket only. Returns {recording, kind, slot, name, bytes, sha256, type, facts}.
 */
export function uploadMedia(p, file, { recording, slot, onProgress, signal } = {}) {
  const headers = { "X-File-Name": encodeURIComponent(file.name) };
  if (recording) headers["X-Recording-Id"] = recording;
  if (slot) headers["X-Slot-Id"] = slot;
  return send("POST", `/projects/${enc(p)}/media`, { blob: file, headers, progress: typeof onProgress === "function" ? onProgress : () => {}, signal });
}

/** GET /projects/{p}/media: {recordings: [...], usage, retention, limits}; with `recording`, that one. */
export function mediaList(p, { recording, signal } = {}) {
  return send("GET", `/projects/${enc(p)}/media`, { query: { recording }, signal });
}

/** POST /projects/{p}/runs/{id}/verdict: {word}. */
export function verdict(p, id, word, options = {}) {
  return send("POST", `/projects/${enc(p)}/runs/${enc(id)}/verdict`, { body: { word }, signal: options.signal });
}

/** POST /projects/{p}/agents/{name}/mode: {mode}. Every route of an unaccepted project answers 412 first. */
export function setMode(p, name, mode, options = {}) {
  return send("POST", `/projects/${enc(p)}/agents/${enc(name)}/mode`, { body: { mode }, signal: options.signal });
}

/** GET /projects/{p}/progress?since=: the only route that takes a query. */
export function progress(p, { since, signal } = {}) {
  return send("GET", `/projects/${enc(p)}/progress`, { query: { since }, signal });
}

/** GET /projects/{p}/agents: {agents: [{name, pack, enabled, mode, acting_mode, max_runs_per_day, max_usd_per_day, runs_today (runs on a subscription or free credential), usd_today (spend of runs on a metered one), billing, caps_in_use: {runs, spend}, queued, ...}]}. */
export function agents(p, options) {
  return send("GET", `/projects/${enc(p)}/agents`, options);
}

/** GET /projects/{p}/conversation?after=&conversation=: {conversation, messages: [{id, role, text, ...}]}, oldest first. */
export function conversation(p, { after, conversation: name, signal } = {}) {
  return send("GET", `/projects/${enc(p)}/conversation`, { query: { after, conversation: name }, signal });
}

/** GET /projects/{p}/skills: the skills in scope with their proof on each model, and the two checks of the proof. */
export function skills(p, options) {
  return send("GET", `/projects/${enc(p)}/skills`, options);
}

/** GET /projects/{p}/costs?since=: {since, rows, caps}; since is a day, YYYY-MM-DD. */
export function costs(p, { since, signal } = {}) {
  return send("GET", `/projects/${enc(p)}/costs`, { query: { since }, signal });
}

/** GET /projects/{p}/connections: the providers, the secrets found (never a value), the image. */
export function connections(p, options) {
  return send("GET", `/projects/${enc(p)}/connections`, options);
}

/** GET /projects/{p}/artifacts: {artifacts: [{path, owner, size, modified_at, bound}], truncated}. */
export function artifacts(p, options) {
  return send("GET", `/projects/${enc(p)}/artifacts`, options);
}

/** GET /projects/{p}/artifact?path=: {path, text, size, modified_at} of one file under docs/ (at most 512 bytes of path). */
export function artifact(p, path, { signal } = {}) {
  return send("GET", `/projects/${enc(p)}/artifact`, { query: { path }, signal });
}

/** GET /projects/{p}/artifact/raw?path=: the bytes of one image under docs/, as a Blob (the media type is the blob's). A refusal is an ApiError whose message is the sentence to show. */
export function artifactRaw(p, path, { signal } = {}) {
  return send("GET", `/projects/${enc(p)}/artifact/raw`, { query: { path }, signal, raw: true });
}

/** GET /projects/{p}/commands: {commands: [{command, arguments, help}]}, the lines `/help` prints, in its order. */
export function commands(p, options) {
  return send("GET", `/projects/${enc(p)}/commands`, options);
}

/** POST /projects/{p}/conversation (job): one turn with the planning agent, {text}. */
export function say(p, text, options = {}) {
  return send("POST", `/projects/${enc(p)}/conversation`, { body: { text }, signal: options.signal });
}

/** POST /projects/{p}/sync (job): {dry_run?, take?, path?}. */
export function sync(p, { dryRun, take, path, signal } = {}) {
  return send("POST", `/projects/${enc(p)}/sync`, { body: { dry_run: dryRun, take, path }, signal });
}

/** POST /projects/{p}/dispatch (job). */
export function dispatch(p, options) {
  return send("POST", `/projects/${enc(p)}/dispatch`, options);
}

/** GET /jobs/{id}: a job again, with state "running", "done" or "failed". */
export function job(id, options) {
  return send("GET", `/jobs/${enc(id)}`, options);
}

// --- jobs ----------------------------------------------------------------------------------------------------------

function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal && signal.aborted) {
      reject(new DOMException("aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(() => {
      if (signal) signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("aborted", "AbortError"));
    };
    if (signal) signal.addEventListener("abort", onAbort, { once: true });
  });
}

/** Resolves at once when the tab is visible (or there is no document); else when it becomes visible. An abort rejects. */
function untilVisible(signal) {
  if (typeof document === "undefined" || !document.hidden) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const done = () => {
      document.removeEventListener("visibilitychange", onChange);
      if (signal) signal.removeEventListener("abort", onAbort);
    };
    const onChange = () => {
      if (document.hidden) return;
      done();
      resolve();
    };
    const onAbort = () => {
      done();
      reject(new DOMException("aborted", "AbortError"));
    };
    if (signal && signal.aborted) {
      reject(new DOMException("aborted", "AbortError"));
      return;
    }
    document.addEventListener("visibilitychange", onChange);
    if (signal) signal.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * Ask for a job every `every` milliseconds (at least 200) until its state is "done" or "failed", and return that last
 * job: job.result holds the operation's result when done, job.error the reason when failed. onUpdate is called with
 * each answer. An ApiError from the poll (a 404 for a job the service forgot, a lost connection) is thrown. While the tab
 * is hidden nothing is asked; the first poll after the tab is visible again happens at once, then the period continues.
 */
export async function pollJob(id, every = 1000, { signal, onUpdate } = {}) {
  const wait = Math.max(200, Number(every) || 1000);
  for (;;) {
    await untilVisible(signal);
    const current = await job(id, { signal });
    if (onUpdate) onUpdate(current);
    if (current.state === "done" || current.state === "failed") return current;
    if (current.state !== "running") throw new ApiError(200, "internal", "The service answered with a job state this page does not know.");
    await sleep(wait, signal);
  }
}
