// The readers of the demo world: for each route the page reads, the answer the service would give, built from the state by filling the
// rows of the fixtures (so the keys are the operations' own). Nothing here changes the state.

import { F } from "./fixtures.js";
import { FLOWS } from "./content.js";
import { ACTIONS, ADAPTER, MAX_PARALLEL_CEILING, MODEL } from "./world-state.js";
import { MODES, clone, fill, notFound, notInDemo, Refusal } from "./util.js";

const REQUEST = F.status.requests[0];
const TASK_ROW = REQUEST.tasks[0];
const FINAL = new Set(["done", "cancelled"]);
export const CLI = "/home/demo/openhora/runtime/cli.py";

const childrenOf = (P, id) => P.tasks.filter((t) => t.parent_id === id);
export const requestsOf = (P) => P.tasks.filter((t) => t.parent_id === null);
const openItems = (P) => P.pending.filter((p) => p.status === "open");
const taskRows = (P) => P.tasks.filter((t) => t.parent_id !== null);
/** The tasks that hold a slot of their agent: running, or waiting for the person (the demo has no answered-then-ready case). */
export const holdsSlot = (t) => t.parent_id !== null && (t.state === "running" || t.state === "waiting");
/** The tasks that run, lowest number first. */
export const runningIds = (P) => taskRows(P).filter((t) => t.state === "running").map((t) => t.id).sort((a, b) => a - b);

/** The sentence the service gives every route of a project whose configuration is not accepted (runtime/ops_core.py _accepted), with its command. */
export function unacceptedRefusal(P) {
  const path = `${P.folder}/docs/workbench/runtime.json`;
  const command = `python3 ${CLI} accept-config --project ${P.folder} --sha256 ${P.configSha}`;
  return new Refusal(412, "not_configured", `the configuration ${path} has the hash ${P.configSha} and the accepted one is ${P.acceptedSha}. Read the file; when it is what you want, run: ${command}`, command);
}

export function listRow(item) {
  const row = fill(F.pending.pending.find((r) => !("plan" in r)), { id: item.id, kind: item.kind, title: item.title, task_id: item.task_id, created_at: item.created_at, agent: item.agent, actions: item.actions.slice() });
  if (item.kind === "plan") {
    return { ...row, plan: { tasks: item.payload.tasks.map((t) => ({ key: t.key, skill: t.skill })), plan_sha256: item.payload.plan_sha256 } };
  }
  return row;
}

function requestRow(P, request) {
  const live = P.routing && P.routing.request === request.id ? fill(F["status-routing"].requests.find((r) => r.routing).routing, { run_id: P.routing.run_id, skill: P.routing.skill, started_at: P.routing.started_at }) : null;
  return fill(REQUEST, {
    id: request.id, flow: request.flow, state: request.state, model: request.model || null, title: request.title, on_board: false, open_comments: 0,
    tasks: childrenOf(P, request.id).map((t) => fill(TASK_ROW, { id: t.id, key: t.key, title: t.title, agent: t.agent, skill: t.skill, state: t.state, note: t.note, on_board: false, open_comments: 0, holds_slot: holdsSlot(t), waiting_for: [] })),
    after: request.after, routing: request.state === "cancelled" ? null : live,
  });
}

/** The ready tasks the last dispatch held, as `status` lists them: {task_id, agent, reason, at, next, commands} (P.held maps a task's number to the word). */
function heldRows(P) {
  return taskRows(P).filter((t) => t.state === "ready" && P.held && P.held[t.id]).sort((a, b) => a.id - b.id)
    .map((t) => ({ task_id: t.id, agent: t.agent, reason: P.held[t.id], at: P.changedAt, next: null, commands: [] }));
}

/** The project's standing instructions as `instructions` answers: the demo has no file (it writes nothing to a project's files), with the keys the operation returns. */
export function instructions() {
  return { path: "docs/workbench/instructions.md", present: false, sha256: null, characters: 0, cap: 4000, problem: null, text: "" };
}

export function status(P) {
  return fill(F.status, {
    config: { path: `${P.folder}/docs/workbench/runtime.json`, sha256: P.configSha },
    requests: requestsOf(P).map((r) => requestRow(P, r)), pending: openItems(P).map(listRow), documents: [], board: null, held: heldRows(P),
  });
}

export function pending(P) {
  return { pending: openItems(P).map(listRow) };
}

export function pendingItem(P, id) {
  const item = P.pending.find((p) => p.id === id);
  if (!item) throw notFound(`no pending decision ${id}`);
  return clone(item);
}

export function task(P, id) {
  const found = P.tasks.find((t) => t.id === id);
  if (!found) throw notFound(`no task ${id}`);
  return fill(F["task-live"], {
    task: clone(found), drop: { web: false, takes: false, line: null }, runs: P.runs.filter((r) => r.task_id === id).map(clone),
    pending: P.pending.filter((p) => p.task_id === id).map(clone),
  });
}

const AUTONOMOUS = ["autonomous", "autonomous-with-policy"];

/** The set-model commands of an agent, as the service gives them: every model of the demo, then auto and default; --consent and --accept where the agent's mode would make the model a consent. */
function modelCommands(P, agent) {
  const ids = (F.skills.models || []).map((m) => m.model);
  return [...ids, "auto", "default"].map((model) => {
    const consent = AUTONOMOUS.includes(agent.mode) && !["auto", "default"].includes(model);
    const line = (F.skills.models || []).find((m) => m.model === model);      // the demo's figures for the model, over all its skills
    const figures = line ? { skills: line.skills, reliable: line.reliable, community_only: line.community_only, expected_cost: line.expected_cost, band: line.band, price: line.price } : {};
    return { model, consent, command: `python3 ${CLI} set-model --project ${P.folder} --agent ${agent.name} --model ${model}${consent ? " --consent --accept" : ""}`, ...figures };
  });
}

export function agents(P) {
  const template = F.agents.agents[0];
  return {
    consent_warning: F.agents.consent_warning,
    default_model: null,
    models: (F.skills.models || []).map((m) => m.model),
    config_sha256: P.configSha,
    agents: P.agents.map((a) => {
      const queued = P.tasks.filter((t) => t.parent_id !== null && t.state === "ready" && t.agent === a.name).length;
      const holders = taskRows(P).filter((t) => t.agent === a.name && holdsSlot(t)).map((t) => t.id).sort((x, y) => x - y);
      const index = MODES.indexOf(a.mode);
      const metered = a.usd > 0;
      return fill(template, {
        name: a.name, pack: a.pack, enabled: a.enabled, mode: a.mode, acting_mode: a.enabled && a.mode !== "stopped" ? a.mode : "stopped",
        max_runs_per_day: a.maxRuns, max_usd_per_day: a.maxUsd, runs_today: a.runs, usd_today: a.usd, runs_without_cost: 0, usd_recorded: a.usd,
        usd_reserved: 0, runs_total_today: a.runs + (metered ? 1 : 0), billing: clone(template.billing), caps_in_use: { runs: true, spend: metered },
        max_parallel: a.maxParallel, max_parallel_ceiling: MAX_PARALLEL_CEILING, holders, slots_held: holders.length,
        queued, held: heldRows(P).filter((h) => h.agent === a.name).length,
        wider: MODES.slice(index + 1).map((mode) => ({ mode, command: `python3 ${CLI} set-mode --project ${P.folder} --agent ${a.name} --mode ${mode} --accept${a.model && a.model !== "auto" && AUTONOMOUS.includes(mode) ? " --consent" : ""}` })),
        model: a.model || null, consent: a.consent || null, config_sha256: P.configSha,
        consent_in_force: Boolean(a.consent && a.model && a.consent.model === a.model && a.consent.mode === a.mode && AUTONOMOUS.includes(a.mode)),
        consent_needed: Boolean(a.model && a.model !== "auto" && AUTONOMOUS.includes(a.mode)),
        model_commands: modelCommands(P, a), recommended_model: F.skills.recommended_model || null,
      });
    }),
  };
}

export function conversation(P, query) {
  const after = Number.parseInt(query.get("after") || "0", 10) || 0;
  return fill(F.conversation, { conversation: "project", messages: P.messages.filter((m) => m.id > after).map(clone) });
}

export function skills(P) {
  const used = {};
  for (const run of P.runs) used[run.skill] = (used[run.skill] || 0) + 1;
  const body = clone(F.skills);
  body.skills = body.skills.map((s) => ({ ...s, runs_here: used[s.name] || 0 }));
  delete body.snapshot;      // where the rows came from is for the fixture, not an answer of the service
  return body;
}

const dayOf = (iso) => iso.slice(0, 10);

export function costs(ctx, P, query) {
  const since = query.get("since") || dayOf(new Date(ctx.now() - 30 * 86400000).toISOString());
  const rowTemplate = F.costs.rows[0];
  const price = clone(F.costs.rows.find((r) => r.price).price);
  const rows = [];
  for (let back = 13; back >= 0; back -= 1) {
    const day = dayOf(new Date(ctx.now() - back * 86400000).toISOString());
    if (day < since) continue;
    P.agents.forEach((a, i) => {
      const runs = back === 0 ? a.runs : (back * 7 + i * 3 + P.name.length) % 5;
      if (!runs) return;
      const usd = a.maxUsd > 0 && a.usd > 0 ? (back === 0 ? a.usd : Math.round(runs * 11) / 100) : null;
      rows.push(fill(rowTemplate, { day, agent: a.name, model: MODEL, adapter: ADAPTER, runs, tokens: runs * 15000, recorded_usd: usd, recomputed_usd: usd, unknown_runs: 0, lower_bound_runs: 0, price }));
    });
  }
  return {
    since, rows,
    caps: P.agents.map((a) => fill(F.costs.caps[0], {
      agent: a.name, max_runs_per_day: a.maxRuns, max_usd_per_day: a.maxUsd, runs_today: a.runs, usd_today: a.usd, runs_without_cost: 0,
      usd_recorded: a.usd, usd_reserved: 0, runs_total_today: a.runs + (a.usd > 0 ? 1 : 0),
    })),
  };
}

export function connections() {
  const body = clone(F.connections);
  const classRow = body.classes[0];
  body.classes = [
    fill(classRow, { class: "integration:vcs", provider: "github", found: true, note: "chosen by configuration", skills: ["ops-pull-request"] }),
    fill(classRow, { class: "integration:design-tool", provider: null, found: false, note: "no provider is installed for this class on this machine", skills: ["design-execute"] }),
    fill(classRow, { class: "publisher:linkedin", provider: "linkedin", found: true, note: "the only implementation", skills: ["mkt-engage", "mkt-publish"] }),
  ];
  const secret = body.secrets[0];
  body.secrets = [
    fill(secret, { name: "LINKEDIN_ACCESS_TOKEN", found: true, where: "secret store" }),
    fill(secret, { name: "VCS_GITHUB_TOKEN", found: true, where: "secret store" }),
    fill(secret, { name: "WB_RUNTIME_KEY_OPENROUTER_API_KEY", found: false, where: null }),
  ];
  body.image = { name: "openhora-eval", present: true, evidence: true };
  body.platform = { machine: "arm64", evidence: "linux/arm64", here: "linux/arm64", same: true };
  return body;
}

export function artifacts(P) {
  return {
    artifacts: P.docs.slice().sort((a, b) => (a.path < b.path ? -1 : 1)).map((d) => fill(F.artifacts.artifacts[0], {
      path: d.path, owner: d.owner, agent: d.agent, size: new TextEncoder().encode(d.text).length, modified_at: d.modified_at, kind: d.kind, bound: false,
    })),
    truncated: false,
  };
}

export function artifact(P, query) {
  const path = query.get("path") || "";
  const doc = P.docs.find((d) => d.path === path);
  if (!doc) throw notFound(`${path || "that path"} is not a document under docs/`);
  return fill(F.artifact, { path: doc.path, text: doc.text, size: new TextEncoder().encode(doc.text).length, modified_at: doc.modified_at });
}

export function artifactRaw() {
  throw notInDemo("An image");
}

export function flows() {
  return { flows: FLOWS.map((f) => fill(F.flows.flows[0], f)) };
}

export function progress(ctx, P) {
  const template = F.progress;
  const requests = requestsOf(P).filter((r) => !FINAL.has(r.state)).map((r) => {
    const kids = childrenOf(P, r.id);
    const count = (state) => kids.filter((t) => t.state === state).length;
    return fill(template.progress.requests[0], {
      id: r.id, title: r.title, state: r.state, total: kids.length, done: count("done"), running: count("running"), waiting: count("waiting"),
      blocked: count("blocked"), failed: count("failed"), next: kids.filter((t) => t.state === "ready").map((t) => t.id),
    });
  });
  const waiting = openItems(P).map((i) => fill(template.progress.waiting_for_you[0], {
    pending_id: i.id, kind: i.kind, task_id: i.task_id, title: i.title, age_hours: Math.max(0, Math.floor((ctx.now() - Date.parse(i.created_at)) / 3600000)),
  }));
  const summary = clone(template.summary);
  summary.tasks_done = P.tasks.filter((t) => t.parent_id !== null && t.state === "done").length;
  summary.deliveries = [];
  summary.runs = { total: P.runs.length, ok: P.runs.filter((r) => r.status === "ok").length, failed: 0, cancelled: 0, by_model: { [MODEL]: P.runs.length }, by_failure: {} };
  const text = `${requests.length} open request${requests.length === 1 ? "" : "s"}, ${waiting.length} waiting for you.`;
  return { progress: { requests, waiting_for_you: waiting, stuck: [] }, summary, text };
}

export function version(state, P) {
  return { version: state.generation * 100000 + P.version, changed_at: P.changedAt };
}

export function projectsList(state) {
  const template = F.projects.projects[0];
  return {
    projects: Object.values(state.projects).map((P) => {
      if (!P.accepted) {
        const { message } = unacceptedRefusal(P);
        const row = fill(template, { id: P.id, name: P.name, folder: P.folder, config: { sha256: P.configSha, accepted: false } });
        delete row.open_pending;
        delete row.running_task;
        delete row.running_tasks;
        delete row.routing_request;
        row.message = message;
        return row;
      }
      return fill(template, {
        id: P.id, name: P.name, folder: P.folder, config: { sha256: P.configSha, accepted: true }, open_pending: openItems(P).length,
        running_tasks: runningIds(P), running_task: runningIds(P).length ? runningIds(P)[0] : null,
        routing_request: P.routing ? P.routing.request : null,
      });
    }),
  };
}

export function versionsList(state) {
  const versions = {};
  for (const P of Object.values(state.projects)) {
    versions[P.id] = P.accepted ? { version: state.generation * 100000 + P.version, changed_at: P.changedAt } : { error: "not_configured" };
  }
  return { versions };
}

export { ACTIONS };
