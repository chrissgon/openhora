// The project's standing instructions (package INSTRUCTIONS), in two places. `createInstructions` is the "Instructions" section of the Building's panel,
// beside Routines: a text field with the file's text, the count against the cap, the short hash, Save, and the refusal shown as the service returned it. The file
// is docs/workbench/instructions.md; only the person writes it, and every model run of the project receives its text in the prompt. `createProposal` is the
// Conversation's block: when the reply of a turn carries `instruction_proposal`, the person's own line is offered with "Add to instructions", a button drawn only
// for a live proposal and only when the page may add (js/permissions.js). The page decides nothing: the cap, the checks, the hash and the compare-and-set are the
// service's; the page sends the text with the hash of the file it read, and shows the sentence of a refusal. Text from the service goes in as text. It lives
// with the Lobby's modules because a write may not be sent from the Building itself (test_interface_files.py); the Building only places it.

import { h } from "../dom.js";
import { failureText } from "../cards/plan-rows.js";
import { can as pageMay } from "../permissions.js";

export const HEAD = "Instructions";
export const LEAD = "Every model run of this project receives this text. It never replaces a skill's stop rules, a confirmation gate or an approval.";
export const NONE = "none";                  // the word the service takes for the base hash of a file that is not there
const REREAD_MS = 15000;                     // read again when older than this, and after every write
const SHORT = 12;                            // characters of the hash shown

/** The characters of a text as the cap counts them: code points, a CRLF counted as one. */
export function countOf(text) {
  return Array.from(String(text || "").replace(/\r\n/g, "\n")).length;
}

/** The line under the field: the count against the cap, and the short hash (or that no file is there yet). */
export function countWords(characters, cap, sha256) {
  const hash = sha256 ? `file ${String(sha256).slice(0, SHORT)}` : "no file yet";
  return `${characters} of ${cap} characters · ${hash}`;
}

/** The hash a Save is based on: the one the service gave when the page read the file, or the word that says there was none. */
export function baseOf(read) {
  return read && typeof read.sha256 === "string" && read.sha256 ? read.sha256 : NONE;
}

/**
 * env: {api (the client), project (getter), entry() (the GET /projects entry, for the policy), refresh()}. Returns {el, update(detail, shown)}.
 */
export function createInstructions(env) {
  const head = h("h3", { class: "wb-steps-head", text: HEAD });
  const lead = h("p", { class: "wb-steps-line", text: LEAD });
  const field = h("textarea", { class: "pui-input wb-field-input wb-in-field", rows: "6", autocomplete: "off", spellcheck: "false", "aria-label": "Standing instructions of the project" });
  const count = h("p", { class: "wb-steps-note wb-in-count", role: "status" });
  const problem = h("p", { class: "notice pui-soft pui-error wb-notice-card wb-in-problem", role: "alert", hidden: true });
  const changed = h("p", { class: "wb-steps-note wb-in-changed", role: "status", hidden: true });
  const error = h("div", { class: "wb-form-error" });
  const actions = h("div", { class: "wb-rt-actions" });
  const el = h("section", { class: "wb-steps-sec wb-in-sec", hidden: true }, head, lead, field, count, problem, changed, error, actions);
  let read = null;                 // the service's answer the field was last filled from
  let latest = null;               // the newest answer, which may differ from `read` when the file changed by hand while the person typed
  let readAt = 0;
  let reading = false;
  let shown = false;
  let busy = false;
  let dirty = false;
  const may = (op) => pageMay(env.entry ? env.entry() : null, op);

  function fail(e) {
    error.replaceChildren(h("p", { class: "notice pui-soft pui-error wb-notice-card", role: "alert", text: failureText(e) }));
  }

  function button(label, onClick, extra = "") {
    const b = h("button", { class: `pui-btn pui-surface pui-outline wb-small-button ${extra}`, type: "button", text: label });
    b.disabled = busy;
    b.addEventListener("click", onClick);
    return b;
  }

  function fillFrom(answer) {
    read = answer;
    latest = answer;
    dirty = false;
    field.value = answer && typeof answer.text === "string" ? answer.text : "";
  }

  async function load(force = false) {
    if (reading || !shown || !(force || Date.now() - readAt >= REREAD_MS)) return;
    reading = true;
    try {
      const answer = await env.api.instructions(env.project);
      readAt = Date.now();
      latest = answer;
      if (!dirty) fillFrom(answer);
    } catch (e) {
      fail(e);
    }
    reading = false;
    draw();
  }

  async function save() {
    if (busy || !may("instructions-set")) return;
    busy = true;
    error.replaceChildren();
    try {
      await env.api.instructionsSet(env.project, field.value, baseOf(read));
      dirty = false;
      if (env.refresh) await env.refresh();
    } catch (e) {
      fail(e);
    }
    busy = false;
    readAt = 0;
    await load(true);
    if (!dirty && !error.children.length) fillFrom(latest);
    draw();
  }

  function draw() {
    el.hidden = !shown;
    if (!shown) return;
    const writable = may("instructions-set");
    field.readOnly = !writable;
    const cap = (latest && latest.cap) || (read && read.cap) || 0;
    count.textContent = countWords(countOf(field.value), cap, latest ? latest.sha256 : null);
    const sentence = latest && latest.problem ? String(latest.problem) : "";
    problem.hidden = !sentence;
    problem.textContent = sentence;
    const moved = dirty && latest && baseOf(latest) !== baseOf(read);
    changed.hidden = !moved;
    changed.textContent = moved ? "The file changed since you opened it. Save will be refused until you reload it; your text stays in the field." : "";
    actions.replaceChildren();
    if (writable) {
      actions.append(button("Save the instructions", save, "wb-in-save"));
      actions.append(button("Reload the file", async () => { error.replaceChildren(); dirty = false; await load(true); draw(); }, "wb-in-reload"));
    } else {
      actions.append(h("p", { class: "wb-steps-line", text: "Writing them is done in the terminal: instructions-set (or instructions-add) with --base-sha256." }));
    }
  }

  field.addEventListener("input", () => { dirty = true; draw(); });

  return {
    el,
    /** detail: the project's entry of the snapshot; shown: whether the panel draws the section at all (the project is accepted). */
    update(detail, isShown) {
      shown = Boolean(isShown && detail);
      draw();
      if (shown) load();
    },
  };
}

/**
 * The Conversation's block for a live proposal. env: {api, project (getter or value), may(op) -> boolean, refresh()}. Returns {el, show(proposal), clear()}.
 * `proposal` is the `instruction_proposal` of a turn's result: {line, base_sha256, command, text}. The line and the hash are the service's, sent back as they came.
 */
export function createProposal(env) {
  const ask = h("p", { class: "wb-steps-line wb-in-ask" });
  const line = h("p", { class: "wb-in-line mono" });
  const result = h("p", { class: "wb-steps-note", role: "status" });
  const error = h("div", { class: "wb-form-error" });
  const actions = h("div", { class: "wb-rt-actions" });
  const el = h("div", { class: "wb-in-proposal pui-soft wb-comp-line", hidden: true }, ask, line, actions, result, error);
  let live = null;
  let busy = false;

  function clear() {
    live = null;
    el.hidden = true;
    actions.replaceChildren();
    error.replaceChildren();
    result.textContent = "";
  }

  async function add() {
    if (busy || !live || !env.may("instructions-add")) return;
    busy = true;
    error.replaceChildren();
    try {
      await env.api.instructionsAdd(typeof env.project === "function" ? env.project() : env.project, live.line, live.base_sha256);
      live = null;
      actions.replaceChildren();
      result.textContent = "Added to the project's instructions.";
      if (env.refresh) await env.refresh();
    } catch (e) {
      error.replaceChildren(h("p", { class: "notice pui-soft pui-error wb-notice-card", role: "alert", text: failureText(e) }));
    }
    busy = false;
  }

  function draw() {
    actions.replaceChildren();
    if (env.may("instructions-add")) {
      const yes = h("button", { class: "pui-btn pui-surface pui-outline wb-small-button wb-in-add", type: "button", text: "Add to instructions" });
      yes.addEventListener("click", add);
      actions.append(yes);
    } else {
      actions.append(h("p", { class: "wb-steps-line", text: `Adding it is done in the terminal: ${live.command}` }));
    }
    const no = h("button", { class: "pui-btn pui-surface pui-outline wb-small-button wb-in-dismiss", type: "button", text: "Not now" });
    no.addEventListener("click", clear);
    actions.append(no);
  }

  return {
    el,
    show(proposal) {
      if (!proposal || typeof proposal.line !== "string" || !proposal.line) return clear();
      live = proposal;
      result.textContent = "";
      error.replaceChildren();
      ask.textContent = "Add this line to the project's instructions?";
      line.textContent = proposal.line;
      el.hidden = false;
      draw();
    },
    clear,
  };
}
