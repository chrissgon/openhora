// The state of the demo world: three projects held in memory, built from the fixtures (the shapes the operations give) and content.js
// (the words). A project holds rows in the shapes the runtime's store gives them; the readers (world-reads.js) turn them into the
// service's answers and the writers (world-writes.js) change them the way the operations do. Nothing here touches the network.

import { F } from "./fixtures.js";
import { PROJECTS } from "./content.js";
import { clone, fill, sha256Hex } from "./util.js";

export const MODEL = "reference-model";
export const MAX_RUNNING = 3;               // the project's limit of tasks at once (runtime.json max_running, default 3)
export const MAX_PARALLEL_CEILING = 4;      // the release's cap of slots on one floor (runtime/autonomy.py MAX_PARALLEL_CEILING)
export const ADAPTER = "adapter";

/** The words (`actions`) an open decision of each kind takes, as the operations give them (runtime/ops.py actions_of). */
export const ACTIONS = Object.freeze({
  plan: ["approved", "rejected"],
  question: ["answered"],
  review: ["answered", "released"],
  effect: ["approved", "rejected"],
  acceptance: ["accepted", "rejected"],
});

const TASK = F["task-live"].task;
const RUN = F["task-live"].runs[0];
const ITEM = F["pending-review"];

export const iso = (ctx, minutes = 0) => new Date(ctx.now() + minutes * 60000).toISOString();

/** The sha256 of the configuration a project holds: its folder and the mode of each agent (what a change of mode changes). */
export function configHash(P) {
  return sha256Hex(`${P.folder}|${P.agents.map((a) => `${a.name}=${a.mode}`).join(",")}`);
}

export function taskRow(ctx, fields) {
  return fill(TASK, {
    parent_id: null, flow: null, key: null, skill: null, agent: null, title: "", text: "", state: "planned", depends_on: [], milestone: 0,
    note: null, created_at: iso(ctx), updated_at: iso(ctx), remote_id: null, remote_version: null, remote_written_sha256: null, after: null,
    waiting_for: [], ...fields,
  });
}

/** Where a run's files are, as the runtime words it: the data folder of the project, then the run's number. */
export const runDir = (P, run) => `/home/demo/.openhora/data/${P.name}/task-runs/${run === null ? 0 : run}`;

export function runRow(ctx, fields) {
  return fill(RUN, {
    skill_version: "1.0.0", skill_sha256: null, model: MODEL, adapter: ADAPTER, web: 0, status: "running", failure: null, ending: null,
    attempts: 0, started_at: iso(ctx), ended_at: null, cost_usd: null, tokens: null, duration_ms: null, skill_loaded: 1, image_digest: null,
    run_dir: null, error: null, redactions: 0, billing: "subscription", ...fields,
  });
}

/** A decision in the shape of `pending` with an id: the fixture of its kind, with the fields the story changes. */
export function itemRow(ctx, P, kind, fields) {
  const base = F[`pending-${kind}`] || ITEM;
  const item = fill(base, {
    id: P.next.pending++, run_id: null, kind, payload_sha256: null, status: "open", resolution: null, answer: null, created_at: iso(ctx),
    resolved_at: null, resolved_by: null, agent: null, actions: ACTIONS[kind].slice(), ...fields,
  });
  return item;
}

/** The payload of a review or a question, from the fixture's, with the paths of the run named by the item. */
export function runPayload(kind, run, P, over = {}) {
  const payload = clone(F[`pending-${kind === "question" ? "question" : "review"}`].payload);
  const dir = runDir(P, run);
  payload.run_dir = dir;
  payload.response_file = `${dir}/outputs/response.md`;
  payload.kept = [];
  payload.returned = [];
  return Object.assign(payload, over);
}

function agentRow(spec) {
  return { name: spec.name, pack: spec.pack, enabled: true, mode: spec.mode, maxRuns: spec.maxRuns, maxUsd: spec.maxUsd, runs: spec.runs, usd: spec.usd, maxParallel: spec.maxParallel || 1 };
}

/** One project, from its spec in content.js. */
export function buildProject(ctx, spec) {
  const P = {
    id: spec.id, name: spec.name, folder: spec.folder, accepted: true, configSha: "", acceptedSha: "", version: 1, changedAt: iso(ctx),
    agents: spec.agents.map(agentRow), tasks: [], runs: [], pending: [], messages: [], docs: [], routing: null, held: {}, verdicts: {}, accept: new Set(), effectDocs: {},
    next: { task: 1, pending: 1, run: 1, message: 1, approval: 1 }, startedAt: iso(ctx),
  };
  for (const request of spec.requests) {
    P.tasks.push(taskRow(ctx, { id: request.id, flow: request.flow, title: request.title, text: request.title, state: request.state, created_at: iso(ctx, -request.ago), updated_at: iso(ctx, -request.ago) }));
    P.next.task = Math.max(P.next.task, request.id + 1);
    for (const t of request.tasks) {
      P.tasks.push(taskRow(ctx, {
        id: t.id, parent_id: request.id, flow: request.flow, key: t.key, skill: t.skill, agent: t.agent, title: t.title, text: t.text, state: t.state,
        depends_on: t.after || [], milestone: 0, created_at: iso(ctx, -t.ago), updated_at: iso(ctx, -t.ago),
      }));
      P.next.task = Math.max(P.next.task, t.id + 1);
    }
  }
  for (const run of spec.runs) {
    const task = P.tasks.find((t) => t.id === run.task);
    P.runs.push(runRow(ctx, {
      id: P.next.run++, task_id: run.task, skill: task.skill, status: run.status, ending: run.ending, attempts: 1, started_at: iso(ctx, -run.ago - run.minutes),
      ended_at: run.status === "running" ? null : iso(ctx, -run.ago), tokens: run.tokens, duration_ms: run.status === "running" ? null : run.minutes * 60000, run_dir: runDir(P, P.next.run - 1),
    }));
  }
  for (const p of spec.pending) {
    const payload = runPayload(p.kind, p.run === null ? null : p.run, P, p.returned ? { returned: p.returned, ending: "done", why: "every declared output is there and nothing is asked" } : { ending: "question", why: "no file changed and the reply asks" });
    P.pending.push(itemRow(ctx, P, p.kind, {
      id: p.id, task_id: p.task, run_id: p.run, title: p.title, body: p.body, payload, agent: p.agent, created_at: iso(ctx, -p.ago),
    }));
    P.next.pending = Math.max(P.next.pending, p.id + 1);
  }
  for (const m of spec.messages) {
    P.messages.push(fill(F.conversation.messages[0], { id: m.id, role: m.role, text: m.text, task_id: m.task || null, run_id: null, created_at: iso(ctx, -m.ago), queued: false }));
    P.next.message = Math.max(P.next.message, m.id + 1);
  }
  for (const d of spec.docs) P.docs.push({ path: d.path, owner: d.owner, agent: d.agent, kind: d.kind, text: d.text, modified_at: iso(ctx, -d.ago) });
  return P;
}

/** The whole state: every project, the jobs, and the counter the change signal grows from. */
export async function buildState(ctx, generation) {
  const projects = {};
  for (const spec of PROJECTS) {
    const P = buildProject(ctx, spec);
    P.configSha = P.acceptedSha = await configHash(P);
    projects[spec.id] = P;
  }
  return { projects, jobs: [], nextJob: 1, generation };
}
