// The writers of the demo world: each write the page sends, applied to the state in memory the way the operation applies it in the runtime
// (runtime/ops.py), with the same refusals and the same answers' keys. An approval is checked against the hash of the exact content,
// computed here with the browser's crypto; nothing is sent anywhere. What the demo does not support is refused with the service's own shape.

import { F } from "./fixtures.js";
import { FLOWS, SPRING } from "./content.js";
import { MAX_RUNNING, configHash, itemRow, iso, runDir, runRow, taskRow } from "./world-state.js";
import { CLI, holdsSlot, progress, requestsOf } from "./world-reads.js";
import { MODES, canonical, fill, notFound, notInDemo, refused, sha256Hex, usage } from "./util.js";

const WORDS = F.writes;
const APPROVAL_WORDS = /^(yes|y|ok|approve|approved|go|proceed|sure)[.!]*$/i;

// The tasks each flow plans (a flow file of the checkout, in the runtime): a key, a skill, the agent that holds it and what it waits for.
const FLOW_TASKS = {
  "launch-page": SPRING.planTasks,
  "fix-bug": [
    { key: "reproduce", skill: "eng-root-cause", agent: "engineering", title: "Reproduce the bug", text: "Find the smallest way to see the bug.", milestone: false, web: false, depends_on: [] },
    { key: "fix", skill: "eng-implement", agent: "engineering", title: "Fix it", text: "Make the smallest change that fixes it.", milestone: true, web: false, depends_on: ["reproduce"] },
    { key: "test", skill: "eng-unit-tests", agent: "engineering", title: "Add a test", text: "Add the test that fails without the fix.", milestone: false, web: false, depends_on: ["fix"] },
  ],
  "write-docs": [
    { key: "draft", skill: "eng-docs", agent: "engineering", title: "Draft the page", text: "Write the page.", milestone: false, web: false, depends_on: [] },
    { key: "check", skill: "eng-unit-tests", agent: "engineering", title: "Check the examples", text: "Run the examples of the page.", milestone: false, web: false, depends_on: ["draft"] },
  ],
};

const find = (P, id) => {
  const item = P.pending.find((p) => p.id === id);
  if (!item) throw notFound(`no pending decision ${id}`);
  return item;
};
const taskOf = (P, id) => P.tasks.find((t) => t.id === id);
const agentOf = (P, name) => P.agents.find((a) => a.name === name) || null;

export function addMessage(ctx, P, role, text, task = null) {
  const message = fill(F.conversation.messages[0], { id: P.next.message++, role, text, task_id: task, run_id: null, created_at: iso(ctx), queued: false });
  P.messages.push(message);
  return message;
}

export function upsertDoc(ctx, P, doc) {
  const kept = P.docs.find((d) => d.path === doc.path);
  if (kept) Object.assign(kept, doc, { modified_at: iso(ctx) });
  else P.docs.push({ ...doc, modified_at: iso(ctx) });
}

function resolve(ctx, item, resolution, answer = null) {
  Object.assign(item, { status: "resolved", resolution, answer, resolved_at: iso(ctx), resolved_by: "user", actions: [] });
}

// --- what a change leads to ---------------------------------------------------------------------------------------------

/** Tasks whose dependencies are done become ready; a request whose tasks are all done is accepted (when its flow asks) or done. Returns the ids made ready. */
export function settle(ctx, P) {
  const ready = [];
  for (const request of requestsOf(P)) {
    const kids = P.tasks.filter((t) => t.parent_id === request.id);
    for (const t of kids) {
      if (t.state !== "planned") continue;
      if (t.depends_on.every((key) => (kids.find((k) => k.key === key) || { state: "done" }).state === "done")) {
        t.state = "ready";
        t.updated_at = iso(ctx);
        ready.push(t.id);
      }
    }
    if (request.state === "planned" && kids.length && kids.every((t) => t.state === "done")) {
      const open = P.pending.some((p) => p.task_id === request.id && p.status === "open");
      if (P.accept.has(request.id) && !open && !P.pending.some((p) => p.task_id === request.id && p.kind === "acceptance")) {
        P.pending.push(itemRow(ctx, P, "acceptance", {
          task_id: request.id, title: `Accept request ${request.id}: ${request.title}`, body: SPRING.acceptance.body,
          payload: { deliveries: [], what: "deliveries" },
        }));
      } else if (!open) {
        request.state = "done";
        request.updated_at = iso(ctx);
      }
    }
  }
  return ready;
}

/**
 * The dispatcher of the runtime, as far as the demo goes (runtime/parallel.py): the ready tasks, oldest first, each start when its floor has a free slot (`maxParallel` of its agent),
 * the project runs fewer than MAX_RUNNING tasks and no running task has the same skill (the same skill writes the same files). A task that waits is recorded with the word the
 * runtime gives (`P.held`), which `status` lists. A router run (`P.routing`) takes no slot and stops nothing. Returns the numbers of the tasks it started.
 */
export function dispatch(ctx, P) {
  const started = [];
  P.held = {};
  const ready = P.tasks.filter((t) => t.parent_id !== null && t.state === "ready").sort((a, b) => a.id - b.id);
  for (const t of ready) {
    const agent = agentOf(P, t.agent);
    if (agent && !(agent.enabled && agent.mode !== "stopped")) continue;
    const running = P.tasks.filter((x) => x.parent_id !== null && x.state === "running");
    let why = null;
    if (running.length >= MAX_RUNNING) why = "project at max_running";
    else if (agent && P.tasks.filter((x) => x.id !== t.id && x.agent === agent.name && holdsSlot(x)).length >= agent.maxParallel) why = "agent at max_parallel";
    else if (running.some((x) => x.skill === t.skill)) why = "artifact in use";
    if (why) {
      P.held[t.id] = why;
      continue;
    }
    t.state = "running";
    t.updated_at = iso(ctx);
    P.runs.push(runRow(ctx, { id: P.next.run++, task_id: t.id, skill: t.skill, run_dir: runDir(P, P.next.run - 1) }));
    if (agent) agent.runs += 1;
    started.push(t.id);
  }
  return started;
}

// --- the plan -----------------------------------------------------------------------------------------------------------

function planTasks(P, flow) {
  const names = P.agents.map((a) => a.name).filter((n) => n !== "planning");
  return (FLOW_TASKS[flow] || FLOW_TASKS["write-docs"]).map((t) => ({
    agent: names.includes(t.agent) ? t.agent : (names[0] || null), depends_on: t.depends_on.slice(), key: t.key, mandatory_milestone: false, milestone: t.milestone,
    skill: t.skill, text: t.text, title: t.title, web: t.web,
  }));
}

/** The router run the project holds ends (one router run at a time, as in the store): its run row is closed. */
export function endRouting(ctx, P) {
  if (!P.routing) return;
  const run = P.runs.find((r) => r.id === P.routing.run_id);
  if (run && run.status === "running") {
    Object.assign(run, { status: "ok", ending: "done", attempts: 1, ended_at: iso(ctx), duration_ms: Math.max(1000, Date.parse(iso(ctx)) - Date.parse(run.started_at)), tokens: 4200 });
  }
  P.routing = null;
}

/** Open the plan of a request that waits for its route: a pending decision of kind `plan`, its hash taken over the tasks. */
export async function openPlan(ctx, P, request, flow, source) {
  const tasks = planTasks(P, flow);
  const digest = await sha256Hex(canonical(tasks));
  const template = F["pending-plan"].payload;
  const keys = Object.fromEntries(tasks.map((t, i) => [t.key, i + 1]));
  const rows = tasks.map((t, i) => `| ${i + 1} | ${t.title} | ${t.skill} | ${t.depends_on.map((k) => keys[k]).join(", ") || "-"} | ${t.milestone ? "yes" : "no"} | no |`);
  const named = source === "named" ? "the flow you named" : `the planning agent's route, the flow ${flow}`;
  const body = [`Plan for request ${request.id}: ${request.title}`, `Source: ${named}; flow file flows/${flow}.json`, "", "| # | Task | Skill | After | Milestone | Web |",
    "|---|---|---|---|---|---|", ...rows, "", `Up to ${MAX_RUNNING} tasks at a time; each run at most 1800 s, retried at most 2 times. At least ${tasks.length} runs.`,
    `Past runs of these skills here: ${tasks.map((t) => `${t.skill} ${P.runs.filter((r) => r.skill === t.skill).length}`).join("; ")}.`, `Plan hash: ${digest}`].join("\n");
  const payload = fill(template, {
    cycles: [], estimate: { past: tasks.map((t) => ({ mean_duration_ms: null, runs: P.runs.filter((r) => r.skill === t.skill).length, skill: t.skill })), runs_at_least: tasks.length, tasks: tasks.length },
    flow, limits: { max_running: MAX_RUNNING, retries: 2, timeout_seconds: 1800 }, missing: [], plan_sha256: digest, route: null, source, tasks, waits: [],
  });
  const item = itemRow(ctx, P, "plan", { task_id: request.id, title: `Plan: ${flow} (${tasks.length} tasks)`, body, payload });
  P.pending.push(item);
  request.flow = flow;
  if (P.routing && P.routing.request === request.id) endRouting(ctx, P);
  addMessage(ctx, P, "assistant", `The planning agent proposes: the flow ${flow}, ${tasks.length} tasks. Approve the plan to start.`, request.id);
  return item;
}

/** A request of the person: the row, the message and, with `route`, the router run that holds it until the plan opens. */
export function newRequest(ctx, P, { text, flow = null, title = null, after = null, model = null, message = false, route = false }) {
  const id = P.next.task++;
  const row = taskRow(ctx, { id, flow, title: title || text.split(/(?<=[.!?])\s|\n/)[0].slice(0, 120), text, state: "requested", after });
  row.model = model;
  P.tasks.push(row);
  if (message) {
    addMessage(ctx, P, "user", text);
    addMessage(ctx, P, "assistant", route ? "Recorded as request " + id + ". The planning agent is routing it." : `Recorded as request ${id}. Press "Route it" to plan it.`, id);
  }
  if (route) {
    endRouting(ctx, P);      // a router run that holds another request ends first: the slot is one, and that request waits for its "Route it"
    P.routing = { request: id, run_id: P.next.run++, skill: "core-orchestrator", started_at: iso(ctx) };
    P.runs.push(runRow(ctx, { id: P.routing.run_id, task_id: id, skill: "core-orchestrator", run_dir: runDir(P, P.routing.run_id) }));
  }
  return row;
}

// --- the writes the page sends -------------------------------------------------------------------------------------------

async function approvePlan(ctx, P, item, body) {
  const stated = item.payload.plan_sha256;
  if ((await sha256Hex(canonical(item.payload.tasks))) !== stated) throw refused(`pending decision ${item.id}: its tasks do not have the hash it states; nothing was approved`);
  if (body.sha256 !== undefined && body.sha256 !== null && body.sha256 !== stated) throw refused(`the plan's hash is ${stated} and you typed ${body.sha256}: nothing was approved`);
  const known = item.payload.tasks.map((t) => t.key);
  const named = Array.isArray(body.go_ahead) ? body.go_ahead : [];
  const unknown = named.filter((k) => !known.includes(k));
  if (unknown.length) throw usage(`go ahead names ${unknown.join(", ")}, which the plan does not have; its tasks are ${known.join(", ")}`);
  const request = taskOf(P, item.task_id);
  resolve(ctx, item, "approved");
  const made = item.payload.tasks.map((t) => taskRow(ctx, {
    id: P.next.task++, parent_id: request.id, flow: item.payload.flow, key: t.key, skill: t.skill, agent: t.agent, title: t.title, text: t.text,
    state: "planned", depends_on: t.depends_on.slice(), milestone: t.milestone ? 1 : 0,
  }));
  P.tasks.push(...made);
  request.state = "planned";
  request.flow = item.payload.flow;
  if (item.payload.flow === "launch-page") P.accept.add(request.id);
  const ready = settle(ctx, P);
  dispatch(ctx, P);
  return fill(WORDS["approve-plan"], {
    request: request.id, tasks: made.map((t) => ({ id: t.id, key: t.key, skill: t.skill, state: t.state === "ready" && ready.includes(t.id) ? "ready" : t.state })),
    ready, waits: [], plan_sha256: stated,
  });
}

async function approveEffect(ctx, P, item, body) {
  if (typeof body.sha256 !== "string" || !body.sha256) throw refused(`pending decision ${item.id} is an effect: it is approved only with its hash, ${item.payload_sha256}`);
  if (body.sha256 !== item.payload_sha256) throw refused(`the effect's hash is ${item.payload_sha256} and you sent ${body.sha256}: nothing was sent`);
  // as for a plan: the hash it states must be the hash of the content it holds, taken again now
  const held = P.effectDocs[item.id];
  if (held && (await sha256Hex(canonical(held))) !== item.payload_sha256) throw refused(`pending decision ${item.id}: its content does not have the hash it states; nothing was sent`);
  resolve(ctx, item, "approved");
  const task = taskOf(P, item.task_id);
  task.state = "done";
  task.updated_at = iso(ctx);
  const ready = settle(ctx, P);
  dispatch(ctx, P);
  return fill(WORDS["approve-effect"], {
    pending_id: item.id, approval_id: P.next.approval++, task_id: task.id, task_state: "done", ready, completed: P.tasks.filter((t) => t.parent_id === null && t.state === "done" && t.id === task.parent_id).map((t) => t.id),
    commit: null, pull_request: null, replayed: false, state: { written: true },
  });
}

export async function approve(ctx, P, id, body) {
  const item = find(P, id);
  if (item.status !== "open") throw refused(`pending decision ${id} is not open: nothing was approved`);
  if (item.kind === "plan") return approvePlan(ctx, P, item, body);
  if (body.go_ahead) throw usage(`pending decision ${id} is a ${item.kind}: go ahead is said on the tasks of a plan`);
  if (item.kind === "effect") return approveEffect(ctx, P, item, body);
  if (item.kind === "acceptance") {
    resolve(ctx, item, "accepted");
    const request = taskOf(P, item.task_id);
    request.state = "done";
    request.updated_at = iso(ctx);
    return fill(WORDS.release, { pending_id: item.id, task_id: request.id, task_state: "done", ready: [] });
  }
  throw usage(`pending decision ${id} is a ${item.kind}: approve takes a plan, an acceptance or an effect; a question or a review is answered or released`);
}

export function reject(ctx, P, id, body) {
  const item = find(P, id);
  if (item.status !== "open") throw refused(`pending decision ${id} is not open: nothing was rejected`);
  if (!["plan", "acceptance", "effect"].includes(item.kind)) throw usage(`pending decision ${id} is a ${item.kind}: reject takes a plan, an acceptance or an effect`);
  if (body.note !== undefined && body.note !== null && (typeof body.note !== "string" || !body.note.trim())) throw usage("the note is text");
  resolve(ctx, item, "rejected", body.note || null);
  if (item.kind === "effect") {
    const task = taskOf(P, item.task_id);
    task.state = "cancelled";
    task.updated_at = iso(ctx);
    return fill(WORDS.release, { pending_id: item.id, task_id: task.id, task_state: "cancelled", ready: [] });
  }
  return cancelRequest(ctx, P, item.task_id, item.id);
}

function cancelRequest(ctx, P, id, pendingId = null) {
  const request = taskOf(P, id);
  const cancelled = [request.id];
  const closed = [];
  request.state = "cancelled";
  for (const t of P.tasks.filter((x) => x.parent_id === id && x.state !== "done")) {
    t.state = "cancelled";
    cancelled.push(t.id);
  }
  for (const p of P.pending.filter((x) => x.task_id === id || cancelled.includes(x.task_id))) {
    if (p.status === "open" && p.id !== pendingId) {
      resolve(ctx, p, "cancelled");
      closed.push(p.id);
    }
  }
  if (P.routing && P.routing.request === id) endRouting(ctx, P);
  return pendingId === null ? fill(WORDS.cancel, { request: id, cancelled, pending: closed }) : fill(WORDS.reject, { pending_id: pendingId, request: id, cancelled, pending: closed });
}

export function cancel(ctx, P, id) {
  const request = taskOf(P, id);
  if (!request || request.parent_id !== null) throw notFound(`no request ${id}`);
  if (request.state === "cancelled") throw refused(`request ${id} is cancelled already`);
  return cancelRequest(ctx, P, id);
}

export function answer(ctx, P, id, body) {
  const item = find(P, id);
  if (typeof body.text !== "string" || !body.text.trim()) throw usage("the answer is text, and it is not empty");
  if (item.status !== "open") throw refused(`pending decision ${id} is not open: it was answered or released already`);
  if (item.kind === "effect" && APPROVAL_WORDS.test(body.text.trim())) {
    throw refused(`pending decision ${id} is an effect: an approval is given with approve --id ${id} --sha256 <its hash>, never as an answer (the next run would read it as the skill's yes)`);
  }
  if (!item.actions.includes("answered")) throw usage(`pending decision ${id} is a ${item.kind}: it is not answered`);
  resolve(ctx, item, "answered", body.text);
  const task = taskOf(P, item.task_id);
  const request = task.parent_id === null;
  if (!request) {
    task.state = "ready";
    task.updated_at = iso(ctx);
    dispatch(ctx, P);
  }
  return fill(WORDS.answer, { pending_id: item.id, task_id: task.id, task_state: request ? task.state : "ready", ready: request ? [] : [], completed: [], state: { written: !request } });
}

export function release(ctx, P, id) {
  const item = find(P, id);
  if (item.kind !== "review") throw refused(`pending decision ${id} is a ${item.kind}: only a review is released`);
  if (item.status !== "open") throw refused(`pending decision ${id} is not open: it was answered or released already`);
  resolve(ctx, item, "released");
  const task = taskOf(P, item.task_id);
  task.state = "done";
  task.updated_at = iso(ctx);
  const ready = settle(ctx, P);
  dispatch(ctx, P);
  return fill(WORDS.release, { pending_id: item.id, task_id: task.id, task_state: "done", ready });
}

export function retry(ctx, P, id) {
  const task = taskOf(P, id);
  if (!task || task.parent_id === null) throw notFound(`no task ${id}`);
  if (!["failed", "blocked"].includes(task.state)) throw refused(`task ${id} is ${task.state}: only a failed or blocked task is made ready again`);
  const previous = task.state;
  task.state = "ready";
  task.note = null;
  task.updated_at = iso(ctx);
  dispatch(ctx, P);
  return fill(WORDS.retry, { task_id: id, state: "ready", previous });
}

export function verdict(ctx, P, id, body) {
  if (!["worked", "corrected", "failed"].includes(body.word)) throw usage("a verdict is one of worked, corrected, failed");
  if (!P.runs.some((r) => r.id === id && r.status === "ok")) throw refused(`run ${id} has no recorded use`);
  if (P.verdicts[id]) throw refused(`run ${id} already has the verdict ${P.verdicts[id]}`);
  P.verdicts[id] = body.word;
  return fill(WORDS.verdict, { run_id: id, use: id.toString(16).padStart(8, "0"), verdict: body.word });
}

export function request(ctx, P, body) {
  if (typeof body.text !== "string" || !body.text.trim()) throw usage("the request is text, and it is not empty");
  const flow = body.flow || null;
  if (flow && !FLOWS.some((f) => f.flow === flow)) throw refused(`there is no flow file ${flow}: the flows are ${FLOWS.map((f) => f.flow).join(", ")}`);
  const known = (F.skills.models || []).map((m) => m.model);
  if (body.model && body.model !== "auto" && !known.includes(body.model)) throw usage(`${body.model} is not a model of evals/eval-gate.json: the lab runs the models the file lists`);
  const row = newRequest(ctx, P, { text: body.text.trim(), flow, title: body.title || null, after: Number.isInteger(body.after) ? body.after : null, model: body.model || null });
  if (!flow) return fill(WORDS.request, { request: row.id, state: "requested", next: "route" });
  // a request with a flow is planned from it at once, and its first task starts
  const tasks = planTasks(P, flow).map((t) => taskRow(ctx, {
    id: P.next.task++, parent_id: row.id, flow, key: t.key, skill: t.skill, agent: t.agent, title: t.title, text: t.text, depends_on: t.depends_on.slice(), milestone: t.milestone ? 1 : 0,
  }));
  P.tasks.push(...tasks);
  row.state = "planned";
  settle(ctx, P);
  dispatch(ctx, P);
  return fill(WORDS["request-flow"], { request: row.id, state: "planned", tasks: tasks.map((t) => ({ id: t.id, key: t.key, skill: t.skill, state: t.state })), waits: [], missing: [], flow });
}

export async function route(ctx, P, id, body) {
  const request = taskOf(P, id);
  if (!request || request.parent_id !== null) throw notFound(`no request ${id}`);
  if (request.state !== "requested") throw refused(`request ${id} is ${request.state}: only a request that waits for its route is routed`);
  if (P.pending.some((p) => p.task_id === id && p.status === "open" && p.kind === "plan")) throw refused(`request ${id} has a plan open already`);
  const flow = body.flow || "launch-page";
  if (!FLOW_TASKS[flow]) throw refused(`there is no flow file ${flow}`);
  const item = await openPlan(ctx, P, request, flow, body.flow ? "named" : "router");
  return fill(WORDS.route, { routed: true, pending_id: item.id, source: item.payload.source, flow, cancelled: [], recovered: [] });
}

export async function say(ctx, P, body) {
  if (typeof body.text !== "string" || !body.text.trim()) throw usage("the line is text, and it is not empty");
  const text = body.text.trim();
  if (text.startsWith("/")) {
    const word = text.split(/\s+/)[0];
    let reply;
    if (word === "/help") reply = ["Commands, one per line:", ...F.commands.commands.map((c) => `${c.command} ${c.arguments}`.trim() + "  " + c.help)].join("\n");
    else if (word === "/status" || word === "/progress") reply = progress(ctx, P).text;
    else if (word === "/pending") reply = P.pending.filter((p) => p.status === "open").map((p) => `#${p.id} ${p.kind}: ${p.title}`).join("\n") || "Nothing waits for you.";
    else reply = `${word} is a command of the terminal. In the demo, try /help, /status or /pending.`;
    addMessage(ctx, P, "user", text);
    addMessage(ctx, P, "assistant", reply);
    return fill(WORDS.say, { reply, request_id: null, pending_id: null, ran: false, queued: false });
  }
  const row = newRequest(ctx, P, { text, message: true, route: true });
  ctx.later(() => ctx.settleRoute(P.id, row.id), 6000);
  return fill(WORDS.say, { reply: `Recorded as request ${row.id}. The planning agent is routing it.`, request_id: row.id, pending_id: null, ran: true, queued: false });
}

export async function setMode(ctx, P, agent, body) {
  if (!MODES.includes(body.mode)) throw usage(`a mode is one of ${MODES.join(", ")}`);
  const row = agentOf(P, agent);
  if (!row) throw usage(`'${agent}' is not an agent of area_agents in ${P.folder}/docs/workbench/runtime.json`);
  if (row.mode === body.mode) return fill(WORDS["set-mode-down"], { agent, mode: body.mode, config_sha256: P.configSha, accepted: true, by: null, next: null });
  const narrowing = MODES.indexOf(body.mode) < MODES.indexOf(row.mode);
  row.mode = body.mode;
  P.configSha = await configHash(P);
  if (narrowing) {
    P.acceptedSha = P.configSha;
    return fill(WORDS["set-mode-down"], { agent, mode: body.mode, config_sha256: P.configSha, accepted: true, by: "code:narrowing", next: null });
  }
  P.accepted = false;
  return fill(WORDS["set-mode-up"], { agent, mode: body.mode, config_sha256: P.configSha, accepted: false, by: null, next: `python3 ${CLI} accept-config --project ${P.folder} --sha256 ${P.configSha}` });
}

/** Fix an agent to a model. In the demo, as in the service, a model fixed on an agent in an autonomous mode is the person's consent, which only the terminal gives: the page gets the warning and the command. */
export async function setModel(ctx, P, agent, body) {
  const row = agentOf(P, agent);
  if (!row) throw usage(`'${agent}' is not an agent of area_agents in ${P.folder}/docs/workbench/runtime.json`);
  const known = (F.skills.models || []).map((m) => m.model);
  const model = body.model;
  if (model !== "auto" && model !== "default" && !known.includes(model)) throw usage(`${model} is not a model of evals/eval-gate.json: the lab runs the models the file lists`);
  const autonomous = row.mode === "autonomous" || row.mode === "autonomous-with-policy";
  if (autonomous && model !== "auto" && model !== "default") {
    throw usage(`${agent} is in ${row.mode} mode, and fixing ${model} on it means its reviews are released without you. ${F.agents.consent_warning} To consent, run this command in the terminal: python3 ${CLI} set-model --project ${P.folder} --agent ${agent} --model ${model} --accept`);
  }
  const narrowing = model === "auto" || model === "default";
  row.model = model === "default" ? null : model;
  P.configSha = await configHash(P);
  if (narrowing) {
    P.acceptedSha = P.configSha;
    return { agent, model: row.model, consent: null, config_sha256: P.configSha, accepted: true, by: "code:narrowing", next: null };
  }
  P.accepted = false;
  return { agent, model: row.model, consent: null, config_sha256: P.configSha, accepted: false, by: null, next: `python3 ${CLI} accept-config --project ${P.folder} --sha256 ${P.configSha}` };
}

export function unsupported(what) {
  throw notInDemo(what);
}

export { resolve };
