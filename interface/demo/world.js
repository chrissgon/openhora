// The demo world: the service, in memory. `handle(method, path, body)` answers a route the page calls with the status and the JSON body the
// service would give (the same keys: the rows are filled from the fixtures), `apply(change)` makes a change of the autopilot's story,
// and `reset()` returns the world to its first state. It has no network, no timer of its own but the one it is given (`later`), and no
// clock but the one it is given (`now`), so a test runs it headless with both fixed.

import { F } from "./fixtures.js";
import { buildState } from "./world-state.js";
import * as reads from "./world-reads.js";
import * as writes from "./world-writes.js";
import { applyStory, storyRequestId } from "./world-story.js";
import { Refusal, clone, fill, notFound, notInDemo } from "./util.js";

const PREFIX = "/api/v1";
const ROUTE = /^\/projects\/([0-9a-f]{12})(?:\/(.*))?$/;
const JOB_FIELDS = F.job;

export function createWorld({ now = () => Date.now(), later = (fn, ms) => setTimeout(fn, ms), cancelLater = (id) => clearTimeout(id) } = {}) {
  let state = null;
  let timers = [];
  let generation = 0;
  let ready = null;

  const ctx = {
    now,
    state: () => state,
    later(fn, ms) {
      const id = later(() => { timers = timers.filter((t) => t !== id); fn(); }, ms);
      timers.push(id);
      return id;
    },
    /** The router's run on a request ends and the plan opens (a timer of `say`; the story's own change does it first). */
    async settleRoute(projectId, requestId) {
      const P = state.projects[projectId];
      const row = P && P.tasks.find((t) => t.id === requestId);
      if (!row || row.state !== "requested" || !P.routing || P.routing.request !== requestId) return;
      if (P.pending.some((p) => p.task_id === requestId && p.kind === "plan")) return;
      await writes.openPlan(ctx, P, row, "launch-page", "router");
      touch(P);
    },
  };

  function touch(P) {
    P.version += 1;
    P.changedAt = new Date(now()).toISOString();
  }

  async function init() {
    for (const id of timers) cancelLater(id);
    timers = [];
    state = await buildState(ctx, generation);
  }

  const started = () => {
    if (!ready) ready = init();
    return ready;
  };

  function startJob(P, op, result) {
    state.jobs.push(null);
    const number = state.nextJob++;
    const stamp = new Date(now()).toISOString();
    const base = fill(JOB_FIELDS, { job: number, op, project: P.id, state: "running", result: null, error: null, started_at: stamp, ended_at: null });
    let final;
    if (result instanceof Refusal) {
      final = { ...base, state: "failed", error: { error: result.word, message: result.message, status: result.status, ...(result.next ? { next: result.next } : {}) }, ended_at: stamp };
    } else {
      final = { ...base, state: "done", result, ended_at: stamp };
    }
    state.jobs[number - 1] = { running: base, final, reads: 0 };
    return base;
  }

  /** A write that is a job in the service: it runs at once here, and its job shows "running" once, then its end. */
  async function job(P, op, work) {
    let outcome;
    try {
      outcome = await work();
    } catch (e) {
      if (!(e instanceof Refusal)) throw e;
      outcome = e;
    }
    touch(P);
    return { status: 202, body: startJob(P, op, outcome) };
  }

  async function plain(P, work) {
    const out = await work();
    touch(P);
    return { status: 200, body: out };
  }

  function idOf(text) {
    return Number.parseInt(text, 10);
  }

  async function projectRoute(P, method, rest, query, body) {
    const parts = rest.split("/");
    const key = `${method} ${parts[0]}`;
    if (!P.accepted) throw reads.unacceptedRefusal(P);
    const get = (value) => ({ status: 200, body: value });
    if (method === "GET") {
      if (parts.length === 1) {
        switch (parts[0]) {
          case "status": return get(reads.status(P));
          case "pending": return get(reads.pending(P));
          case "agents": return get(reads.agents(P));
          case "conversation": return get(reads.conversation(P, query));
          case "skills": return get(reads.skills(P));
          case "costs": return get(reads.costs(ctx, P, query));
          case "connections": return get(reads.connections(P));
          case "artifacts": return get(reads.artifacts(P));
          case "artifact": return get(reads.artifact(P, query));
          case "flows": return get(reads.flows());
          case "progress": return get(reads.progress(ctx, P));
          case "version": return get(reads.version(state, P));
          case "commands": return get(clone(F.commands));
          case "instructions": return get(reads.instructions());
          default: break;
        }
      }
      if (parts[0] === "pending" && parts.length === 2) return get(reads.pendingItem(P, idOf(parts[1])));
      if (parts[0] === "tasks" && parts.length === 2) return get(reads.task(P, idOf(parts[1])));
      if (parts[0] === "artifact" && parts[1] === "raw") reads.artifactRaw();
      throw notFound("no such route, project or file");
    }
    if (method !== "POST") throw new Refusal(405, "method", "this path does not take that method");
    if (parts[0] === "pending" && parts.length === 3) {
      const id = idOf(parts[1]);
      switch (parts[2]) {
        case "answer": return plain(P, async () => writes.answer(ctx, P, id, body));
        case "release": return job(P, "release", async () => writes.release(ctx, P, id));
        case "approve": return job(P, "approve", async () => writes.approve(ctx, P, id, body));
        case "reject": return plain(P, async () => writes.reject(ctx, P, id, body));
        default: break;
      }
    }
    if (parts[0] === "requests" && parts.length === 1) return plain(P, async () => writes.request(ctx, P, body));
    if (parts[0] === "requests" && parts.length === 3) {
      const id = idOf(parts[1]);
      if (parts[2] === "route") return job(P, "route", async () => writes.route(ctx, P, id, body));
      if (parts[2] === "cancel") return plain(P, async () => writes.cancel(ctx, P, id));
    }
    if (parts[0] === "tasks" && parts.length === 3) {
      const id = idOf(parts[1]);
      if (parts[2] === "retry") return plain(P, async () => writes.retry(ctx, P, id));
      if (parts[2] === "go-ahead") throw notInDemo("Going ahead on a task that waits for another request");
      if (parts[2] === "files") throw notInDemo("Handing a file to a task");
    }
    if (parts[0] === "runs" && parts[2] === "verdict") return plain(P, async () => writes.verdict(ctx, P, idOf(parts[1]), body));
    if (parts[0] === "agents" && parts[2] === "mode") return plain(P, async () => writes.setMode(ctx, P, parts[1], body));
    if (parts[0] === "agents" && parts[2] === "model") return plain(P, async () => writes.setModel(ctx, P, parts[1], body));
    if (parts[0] === "agents" && parts[2] === "consent") return plain(P, async () => writes.giveConsent(ctx, P, parts[1], body));
    if (key === "POST conversation") return job(P, "say", async () => writes.say(ctx, P, body));
    if (parts[0] === "instructions") throw notInDemo("Writing the project's instructions");
    if (key === "POST sync") throw notInDemo("Syncing with the platform");
    if (key === "POST dispatch") throw notInDemo("Running the next task");
    throw notFound("no such route, project or file");
  }

  /** The answer to one request: {status, body}. `path` is the path without the query, `query` a URLSearchParams, `body` the parsed JSON object. */
  async function handle(method, path, query = new URLSearchParams(), body = {}) {
    await started();
    try {
      if (!path.startsWith(PREFIX)) throw notFound("no such route, project or file");
      const bare = path.slice(PREFIX.length);
      if (bare === "/projects" && method === "GET") return { status: 200, body: reads.projectsList(state) };
      if (bare === "/versions" && method === "GET") return { status: 200, body: reads.versionsList(state) };
      const found = /^\/jobs\/([0-9]{1,9})$/.exec(bare);
      if (found && method === "GET") {
        const entry = state.jobs[Number(found[1]) - 1];
        if (!entry) throw notFound("no such job");
        entry.reads += 1;
        return { status: 200, body: clone(entry.reads === 1 ? entry.running : entry.final) };
      }
      const match = ROUTE.exec(bare);
      if (!match || !match[2]) throw notFound("no such route, project or file");
      const P = state.projects[match[1]];
      if (!P) throw notFound("no such project");
      return await projectRoute(P, method, match[2], query, body && typeof body === "object" ? body : {});
    } catch (e) {
      if (e instanceof Refusal) return { status: e.status, body: { error: e.word, message: e.message, ...(e.next ? { next: e.next } : {}) } };
      throw e;
    }
  }

  return {
    handle,
    /** One change of the autopilot's story (world-story.js). */
    async apply(change) {
      await started();
      await applyStory(ctx, change);
      for (const P of Object.values(state.projects)) touch(P);
    },
    /** The number of the story's request in the world as it stands, or null. */
    async storyRequest() {
      await started();
      return storyRequestId(ctx);
    },
    /** Back to the first state. The change signal keeps growing, so a page that is open reloads. */
    async reset() {
      await started();
      generation += 1;
      await init();
    },
    /** The state as plain data (for a test), the sets as lists. */
    async dump() {
      await started();
      return JSON.parse(JSON.stringify(state, (_key, value) => (value instanceof Set ? [...value] : value)));
    },
    ready: started,
  };
}
