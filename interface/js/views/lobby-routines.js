// The routines of the project (package P6b), a section of the Building's panel: the list of routines, "New routine" (a flow, a schedule, a model), and for each
// routine its approval, pause, resume and cancel. A routine is a flow started by a schedule; it is a draft until the person approves the sha256 of its exact content,
// which the service computes and this page shows whole beside the button. The page decides nothing: it sends what was typed or clicked and shows the service's sentence for
// a refusal. When the model is fixed and has no evidence the preview carries the consent's warning (the agent consent's text, whole) and a button that gives the routine's own
// consent, which changes the content and so its hash; the approval is a second, separate click on the new hash. Pause and cancel are brakes and are never withheld; the other
// writes are drawn only when the page may (js/permissions.js). It lives with the Lobby's modules because a write may not be sent from the Building itself
// (test_interface_files.py); the Building only places it. Text from the service goes in as text.

import { h } from "../dom.js";
import { failureText } from "../cards/plan-rows.js";
import { can as pageMay } from "../permissions.js";

export const HEAD = "Routines";
export const EMPTY = "No routine yet. A routine starts a flow on a schedule, after you approve its exact content.";
const REREAD_MS = 15000;      // the list is read again when it is older than this, and after every write

/** The words of a schedule: "every day at 08:00", "every Monday at 08:00", "every 30 minutes". */
export function scheduleWords(schedule) {
  const days = ["", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  if (!schedule || typeof schedule !== "object") return "";
  if (schedule.every === "minutes") return `every ${schedule.minutes} minutes`;
  if (schedule.every === "week") return `every ${days[schedule.weekday] || "week"} at ${schedule.at}`;
  return `every day at ${schedule.at}`;
}

/** The line of a routine's state: its state, and for an active one whether its content is the approved one. */
export function stateWords(r) {
  if (r.state === "active") return r.current === false ? "active, but its content changed since you approved it" : "active";
  return { draft: "draft: not approved", paused: "paused", stopped: "stopped: approve its new content", cancelled: "cancelled" }[r.state] || String(r.state);
}

/**
 * The lines of a routine's content as the person approves it, next to the hash: the schedule, the flow with its template hash, the fixed arguments, the skills with
 * their X.Y, the eval image's digest, the model and the consent, the providers. `content` is the service's (`routines --id`), shown as it is.
 */
export function contentLines(content) {
  const c = content && typeof content === "object" ? content : {};
  const flow = c.flow || {};
  const args = flow.params && typeof flow.params === "object" ? Object.entries(flow.params).map(([k, v]) => `${k}=${v}`).join(", ") : "";
  const skills = c.skills && typeof c.skills === "object" ? Object.entries(c.skills).map(([k, v]) => `${k} ${v}`).join(", ") : "";
  const consent = c.consent && c.consent.given ? "given by you for this model" : "not given";
  return [
    ["Schedule", `${scheduleWords(c.schedule)}${c.schedule && c.schedule.window_seconds ? `, a missed slot is made up for ${c.schedule.window_seconds} s` : ""}`],
    ["Flow", `${flow.name || ""} (template ${flow.template_sha256 || ""})`],
    ["Fixed arguments", args || "none"],
    ["Skills", skills || "none"],
    ["Eval image", String(c.image || "")],
    ["Model", String(c.model || "")],
    ["Consent", consent],
    ["Providers", Array.isArray(c.providers) && c.providers.length ? c.providers.join(", ") : "none"],
  ];
}

/** The fire line: the last slot and what became of it. */
export function fireWords(fire) {
  if (!fire) return "not fired yet";
  return `${fire.slot}: ${fire.status}${fire.reason ? ` (${fire.reason})` : ""}`;
}

/**
 * env: {api (the client), project (getter), entry() (the GET /projects entry, for the policy), refresh()}. Returns {el, update(detail, shown)}.
 */
export function createRoutines(env) {
  const head = h("h3", { class: "wb-steps-head", text: HEAD });
  const list = h("ul", { class: "wb-rt-list", "aria-label": "Routines" });
  const empty = h("p", { class: "wb-steps-line", text: EMPTY, hidden: true });
  const error = h("div", { class: "wb-form-error" });
  const preview = h("div", { class: "wb-rt-preview", hidden: true });
  const form = h("details", { class: "wb-disclosure wb-rt-new", hidden: true }, h("summary", { class: "wb-summary", text: "New routine" }));
  const el = h("section", { class: "wb-steps-sec wb-rt-sec", hidden: true }, head, empty, list, preview, form, error);
  let items = [];
  let flows = [];
  let readAt = 0;
  let reading = false;
  let shown = false;
  let busy = false;
  const may = (op) => pageMay(env.entry ? env.entry() : null, op);

  function fail(e) {
    error.replaceChildren(h("p", { class: "notice pui-soft pui-error wb-notice-card", role: "alert", text: failureText(e) }));
  }

  async function act(call) {
    if (busy) return;
    busy = true;
    error.replaceChildren();
    try {
      await call();
      if (env.refresh) await env.refresh();
    } catch (e) {
      fail(e);
    }
    busy = false;
    await read(true);
  }

  async function read(force = false) {
    if (reading || !shown || !(force || Date.now() - readAt >= REREAD_MS)) return;
    reading = true;
    try {
      const got = await env.api.routines(env.project);
      items = Array.isArray(got && got.routines) ? got.routines : [];
      const known = await env.api.flows(env.project);      // read again each time: a flow saved since is offered
      flows = (Array.isArray(known && known.flows) ? known.flows : []).filter((f) => f && !f.error && !(f.params || []).some((p) => p.type === "file"));
      readAt = Date.now();
    } catch (e) {
      fail(e);
    }
    reading = false;
    draw();
  }

  function button(label, onClick, extra = "") {
    const b = h("button", { class: `pui-btn pui-surface pui-outline wb-small-button ${extra}`, type: "button", text: label });
    b.disabled = busy;
    b.addEventListener("click", onClick);
    return b;
  }

  async function open(r) {
    error.replaceChildren();
    try {
      const got = await env.api.routines(env.project, { id: r.id });
      drawPreview(got);
    } catch (e) {
      fail(e);
    }
  }

  /** What approving needs: the content's hash whole, the consent's warning when the model is fixed and unproven, and the two buttons. */
  function drawPreview(got) {
    const a = got.approve;
    preview.hidden = !a;
    if (!a) return;
    const rows = [h("strong", { text: `Approve ${got.name}` }), h("p", { class: "wb-steps-line", text: `${scheduleWords(got.schedule)} · flow ${got.flow} · model ${got.model_word}` }),
      h("span", { class: "wb-card-label", text: "Hash of its exact content" }), h("code", { class: "wb-hash mono", "data-hash": "routine", tabindex: "0", text: a.sha256 }),
      h("dl", { class: "wb-rt-content", "aria-label": "What the hash covers" }, contentLines(got.content).flatMap(([k, v]) => [h("dt", { text: k }), h("dd", { class: "mono", text: v })]))];
    if (a.consent_needed && may("routine-change")) {
      rows.push(h("p", { class: "wb-steps-line", "data-key": "warning", text: a.warning }));
      rows.push(button("Give this routine's consent", () => act(async () => {
        const changed = await env.api.routineChange(env.project, got.id, { consent: true, warning_sha256: a.warning_sha256 });
        drawPreview(await env.api.routines(env.project, { id: changed.id }));
      }), "wb-rt-consent"));
    } else if (a.consent_needed) {
      rows.push(h("p", { class: "wb-steps-line", text: "Its model has no evidence for these skills: its tasks wait at their first review. Giving the routine's consent is done in the terminal: routine-change --id " + got.id + " --consent." }));
    }
    if (may("routine-approve")) {
      rows.push(button("Approve this exact content", () => act(async () => {
        await env.api.routineApprove(env.project, got.id, a.sha256);
        preview.hidden = true;
      }), "wb-rt-approve"));
    } else {
      rows.push(h("p", { class: "wb-steps-line", text: `Approving is done in the terminal: ${a.command}` }));
    }
    rows.push(button("Close", () => { preview.hidden = true; }));
    preview.replaceChildren(...rows);
  }

  function drawList() {
    empty.hidden = items.length > 0;
    list.replaceChildren(...items.map((r) => {
      const actions = h("div", { class: "wb-rt-actions" });
      if (r.state === "draft" || r.state === "stopped") actions.append(button("Review and approve", () => open(r)));
      if (r.state === "active") actions.append(button("Pause", () => act(() => env.api.routinePause(env.project, r.id))));
      if (r.state === "paused" && may("routine-resume")) actions.append(button("Resume", () => act(() => env.api.routineResume(env.project, r.id))));
      if (r.state !== "cancelled") actions.append(button("Cancel", () => act(() => env.api.routineCancel(env.project, r.id))));
      return h("li", { class: "wb-rt-item" },
        h("strong", { text: r.name }), h("span", { class: "wb-muted", text: ` · ${r.flow} · ${scheduleWords(r.schedule)}` }),
        h("p", { class: "wb-steps-line", text: stateWords(r) }), h("p", { class: "wb-steps-note", text: fireWords(r.last_fire) }), actions);
    }));
  }

  /** "New routine": the fields of a routine, sent as typed; the service checks the flow, the schedule and the model. */
  function drawForm() {
    form.hidden = !may("routine-create");
    if (form.hidden) return;
    const name = h("input", { class: "pui-input wb-field-input", type: "text", autocomplete: "off", "aria-label": "Name of the routine" });
    const flow = h("select", { class: "pui-input wb-select", "aria-label": "Flow" }, flows.map((f) => h("option", { value: f.flow, text: f.title || f.flow })));
    const every = h("select", { class: "pui-input wb-select", "aria-label": "Every" }, ["day", "week", "minutes"].map((w) => h("option", { value: w, text: w })));
    const at = h("input", { class: "pui-input wb-field-input", type: "text", value: "08:00", "aria-label": "At (HH:MM)" });
    const weekday = h("input", { class: "pui-input wb-field-input", type: "text", value: "1", "aria-label": "Weekday (1 Monday to 7 Sunday)" });
    const minutes = h("input", { class: "pui-input wb-field-input", type: "text", value: "60", "aria-label": "Minutes (15 to 720, dividing 1440)" });
    const model = h("input", { class: "pui-input wb-field-input", type: "text", "aria-label": "Model (an id, auto, or empty for the project's default)" });
    const providers = h("input", { class: "pui-input wb-field-input", type: "text", "aria-label": "Providers for auto, separated by commas" });
    const params = h("input", { class: "pui-input wb-field-input", type: "text", "aria-label": "Fixed arguments, name=value separated by commas" });
    const send = button("Create the routine (a draft)", () => act(async () => {
      const fields = { name: name.value.trim(), flow: flow.value, every: every.value };
      if (every.value === "minutes") fields.minutes = Number(minutes.value);
      else fields.at = at.value.trim();
      if (every.value === "week") fields.weekday = Number(weekday.value);
      if (model.value.trim()) fields.model = model.value.trim();
      const chosen = providers.value.split(",").map((t) => t.trim()).filter(Boolean);
      if (chosen.length) fields.providers = chosen;
      const given = params.value.split(",").map((t) => t.trim()).filter(Boolean);
      if (given.length) fields.params = given;
      await env.api.routineCreate(env.project, fields);
      name.value = "";
    }));
    const labelled = (text, input) => h("label", { class: "pui-field-group wb-field" }, h("span", { text }), input);
    form.replaceChildren(h("summary", { class: "wb-summary", text: "New routine" }), h("div", { class: "wb-card-body" },
      labelled("Name", name), labelled("Flow", flow), labelled("Every", every), labelled("At", at), labelled("Weekday", weekday), labelled("Minutes", minutes),
      labelled("Model", model), labelled("Providers (for auto)", providers), labelled("Fixed arguments", params), send));
  }

  function draw() {
    el.hidden = !shown;
    if (!shown) return;
    drawList();
    if (!form.open) drawForm();
  }

  return {
    el,
    /** detail: the project's entry of the snapshot; shown: whether the panel draws the section at all (the project is accepted). */
    update(detail, isShown) {
      shown = Boolean(isShown && detail);
      draw();
      if (shown) read();
    },
  };
}
