// Reading what the City needs from the service: the project list, and for each accepted project its status (which holds
// the requests with their tasks, each with its title and agent, and the open decisions, each with its agent) and its
// agents, then the `task` body of the one running task of the followed project's open request, for the time its run
// started. Everything is read; nothing is written. A project that answers 412 (its configuration is not accepted) is
// kept with the service's own message and with the last status and agents read (the page keeps showing them, dimmed); a lost
// connection throws.

import * as api from "./api.js";
import { neededTasks, taskKey } from "./model.js";

/** A new snapshot holder: {projects, details, tasks, loaded}. */
export function emptySnapshot() {
  return { projects: [], details: {}, tasks: {}, loaded: false };
}

/**
 * One project's status and agents. A 412 (not accepted) is kept as the project's error with the service's text, together with the last
 * status and agents read (A-16: the screen keeps its data until the configuration is accepted). Any other refusal of one project (a
 * 409, a 500) keeps what the last read held, when there is one, so one bad read does not blank a building; the next poll reads again.
 */
async function readProject(project, before, listedAccepted = true) {
  try {
    // A project listed as not accepted is asked one thing, its status: the 412 answer carries the command that accepts it (`next`).
    let status;
    let agents;
    if (listedAccepted) [status, agents] = await Promise.all([api.status(project.id), api.agents(project.id)]);
    else {
      status = await api.status(project.id);
      agents = await api.agents(project.id);     // accepted since the list was read
    }
    return { status, agents: Array.isArray(agents.agents) ? agents.agents : [] };
  } catch (e) {
    if (e && e.name === "ApiError" && e.status !== 0 && e.status !== 401) {
      const error = { status: e.status, word: e.word, message: e.message, next: e.next || null };
      if (before && before.status) return { status: before.status, agents: before.agents, error };   // the data stays, the page says why it is old
      return { error };
    }
    throw e;
  }
}

/**
 * Read everything again and return the new snapshot. `previous` is the last one (its task bodies are reused while a task's
 * state is unchanged, unless `options.force` is set: the page reloads because the store changed, and a running task's runs
 * change while its state does not); `followed` is the id of the project the tracking bar follows.
 */
export async function refresh(previous, followed, options = {}) {
  const listed = await api.projects();
  const projects = Array.isArray(listed.projects) ? listed.projects : [];
  const read = await Promise.all(projects.map((p) => readProject(p, previous.details[p.id], Boolean(p.config && p.config.accepted))));
  const details = {};
  projects.forEach((p, i) => { details[p.id] = read[i]; });
  const wanted = neededTasks(projects, details, followed);
  const tasks = {};
  await Promise.all(wanted.map(async (w) => {
    const key = taskKey(w.project, w.id);
    const cached = previous.tasks[key];
    const refusing = details[w.project] && details[w.project].error && details[w.project].error.status === 412;
    if (refusing) {     // not accepted: the body read before stays, and the project is not asked again on every reload
      if (cached) tasks[key] = cached;
      return;
    }
    if (!options.force && cached && cached.task && (w.state === undefined || cached.task.state === w.state)) {
      tasks[key] = cached;
      return;
    }
    try {
      tasks[key] = await api.task(w.project, w.id);
    } catch (e) {
      if (e && e.name === "ApiError" && e.status === 0) throw e;
      if (e && e.unauthorized) throw e;
      if (cached) tasks[key] = cached;       // not accepted (412): the body read before stays
      // a task that cannot be read leaves its agent and title unknown: the page falls back to the key and the project
    }
  }));
  return { projects, details, tasks, loaded: true };
}

/**
 * The change signal of every project, as one string that is equal while nothing was written: the numbers the service answers to
 * `GET /versions` (or, for a project it could not read, its sentence). One request whatever the number of projects.
 */
export async function versionKey() {
  const got = await api.versions();
  const entries = Object.entries((got && got.versions) || {}).map(([id, v]) => [id, v && v.version !== undefined ? v.version : (v && v.error) || null]);
  return JSON.stringify(entries.sort((a, b) => (a[0] < b[0] ? -1 : 1)));
}
