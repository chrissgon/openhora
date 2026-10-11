// The changes the autopilot makes to the world (scenario.js names them): each is a state the runtime really reaches, put there by the same
// rules the visitor's own writes follow, and each is safe to apply twice or out of order (it looks at the state first and does nothing
// when its change is already there). The request of the story is "Spring sale page" in northwind-shop.

import { F } from "./fixtures.js";
import { SPRING } from "./content.js";
import { itemRow, iso, runPayload } from "./world-state.js";
import { approve, dispatch, newRequest, openPlan, release, settle, upsertDoc } from "./world-writes.js";
import { canonical, clone, sha256Hex } from "./util.js";

export const STORY_PROJECT = "3f9a1c07d2b4";

const request = (P) => P.tasks.find((t) => t.parent_id === null && t.title === SPRING.title && t.state !== "cancelled") || null;
const taskOf = (P, req, key) => (req ? P.tasks.find((t) => t.parent_id === req.id && t.key === key) || null : null);
const itemOf = (P, id, kind) => P.pending.find((p) => p.task_id === id && p.kind === kind) || null;
const runOf = (P, task) => P.runs.filter((r) => r.task_id === task.id && r.status === "running").pop() || null;

/** Start a task that is ready (or running already) and return its run. */
function running(ctx, P, task) {
  if (task.state === "ready") dispatch(ctx, P);
  return task.state === "running" ? runOf(P, task) : null;
}

function endRun(ctx, P, run, ending, tokens) {
  Object.assign(run, { status: "ok", ending, attempts: 1, ended_at: iso(ctx), duration_ms: Math.max(1000, Date.parse(iso(ctx)) - Date.parse(run.started_at)), tokens });
}

const OPS = {
  /** The person types the request in the Lobby: the line, the planning agent's note and the router run that holds it. */
  async "type-request"(ctx, P) {
    if (request(P)) return;
    newRequest(ctx, P, { text: SPRING.title, message: true, route: true });
  },

  /** The router's run ends and the plan opens, its hash taken over its tasks. */
  async "open-plan"(ctx, P) {
    const req = request(P);
    if (!req || req.state !== "requested" || itemOf(P, req.id, "plan")) return;
    await openPlan(ctx, P, req, SPRING.flow, "router");
  },

  /** The plan is approved with its own hash, as the page's button sends it. */
  async "approve-plan"(ctx, P) {
    const req = request(P);
    const plan = req && itemOf(P, req.id, "plan");
    if (!plan || plan.status !== "open") return;
    await approve(ctx, P, plan.id, { sha256: plan.payload.plan_sha256 });
  },

  /** The engineering task ends: its files are there and a review waits for the person. */
  async "finish-build"(ctx, P) {
    const req = request(P);
    const task = taskOf(P, req, "build-page");
    if (!task || itemOf(P, task.id, "review")) return;
    const run = running(ctx, P, task);
    if (!run) return;
    endRun(ctx, P, run, "done", 31800);
    task.state = "waiting";
    task.updated_at = iso(ctx);
    const returned = SPRING.review.returned.map(clone);
    P.pending.push(itemRow(ctx, P, "review", {
      task_id: task.id, run_id: run.id, title: SPRING.review.title, body: SPRING.review.body, agent: task.agent,
      payload: runPayload("review", run.id, P, { returned, ending: "done", why: "every declared output is there and nothing is asked" }),
    }));
    upsertDoc(ctx, P, { path: "docs/engineering/spring-sale-page.md", owner: "eng-implement", agent: "engineering", kind: "markdown", text: SPRING.review.doc });
  },

  /** The review is released: the task is done, and the next one starts. */
  async "release-build"(ctx, P) {
    const req = request(P);
    const task = taskOf(P, req, "build-page");
    const review = task && itemOf(P, task.id, "review");
    if (!review || review.status !== "open") return;
    release(ctx, P, review.id);
  },

  /** The marketing task stops at its gate: an effect, with the hash of its exact content. */
  async "open-effect"(ctx, P) {
    const req = request(P);
    const task = taskOf(P, req, "sale-post");
    if (!task || itemOf(P, task.id, "effect")) return;
    const run = running(ctx, P, task);
    if (!run) return;
    endRun(ctx, P, run, "gate", 12400);
    task.state = "waiting";
    task.updated_at = iso(ctx);
    const doc = { kind: "publish", account: SPRING.effect.account, text: SPRING.effect.text };
    const digest = await sha256Hex(canonical(doc));
    const dir = run.run_dir;
    const payload = clone(F["pending-effect"].payload);
    Object.assign(payload, {
      effect: { opened: true }, effect_file: `${dir}/effect.json`, payload_file: `${dir}/payload.md`, run_dir: dir, response_file: `${dir}/outputs/response.md`,
      gate: { parsed: true, payload_file: `${dir}/payload.md`, payload_sha256: digest, recovered: true, tmp_left: [], why: null }, returned: [], kept: [],
      why: "the run wrote the file of its confirmation gate and asks for approval",
    });
    const body = [
      "Code publishes this post after your approval, and nothing else:", "", `Account: ${doc.account}`, "Post:", doc.text, "", `Hash of this effect: ${digest}`,
      `Approve exactly this: python3 runtime/cli.py approve --project <project> --id <this pending decision's id> --sha256 ${digest}`,
      "Or answer with what to change, or reject it: nothing is sent until you approve.", "",
    ].join("\n");
    P.pending.push(itemRow(ctx, P, "effect", { task_id: task.id, run_id: run.id, title: SPRING.effect.title, body, payload, payload_sha256: digest, agent: task.agent }));
    upsertDoc(ctx, P, { path: "docs/marketing/sale-post.md", owner: "mkt-social-copy", agent: "marketing", kind: "markdown", text: SPRING.effect.doc });
  },

  /** The effect is approved with its own hash; the request waits for the person's acceptance. */
  async "approve-effect"(ctx, P) {
    const req = request(P);
    const task = taskOf(P, req, "sale-post");
    const effect = task && itemOf(P, task.id, "effect");
    if (!effect || effect.status !== "open") return;
    await approve(ctx, P, effect.id, { sha256: effect.payload_sha256 });
  },

  /** The acceptance of the request is accepted: the request is done. */
  async "approve-acceptance"(ctx, P) {
    const req = request(P);
    if (req && req.state === "planned") settle(ctx, P);
    const card = req && itemOf(P, req.id, "acceptance");
    if (!card || card.status !== "open") return;
    await approve(ctx, P, card.id, {});
  },
};

export const OP_NAMES = Object.keys(OPS);

/** Apply one change of the story to the project it names (the story's project when none). */
export async function applyStory(ctx, op) {
  const run = OPS[op.op];
  if (!run) throw new Error(`the story has no change named ${op.op}`);
  const P = ctx.state().projects[op.project || STORY_PROJECT];
  await run(ctx, P, op);
}
