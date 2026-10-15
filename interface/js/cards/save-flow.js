// "Save this plan as a workflow" (decision D32, package P6a): under the resolved line of a plan the person approved, a disclosure with a name
// field and the button that saves the plan as a workflow of the project (docs/workbench/flows/). The page decides nothing: the service saves
// it, runs the flow check first, and refuses a plan the check does not pass with its sentence; when that sentence offers the split the code
// makes (a research task with the web and no source, then the skill without the web), a second button asks for it. Scheduling the workflow
// is the routine's own screen (package P6b). The control is drawn only when the page may save a workflow (`can("flow-save")`, js/permissions.js: the
// project's group `workflows`). Text from the service goes in as text; the field is checked here only for the shape of a name, which the service
// checks again.

import { h } from "../dom.js";
import { failureText } from "./plan-rows.js";

const NAME = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const NAME_MAX = 40;
const OFFER = /split it/i;      // the service's refusal says "the code can split it" when every finding has a split

let counter = 0;

/** A workflow name from a title: lowercase words joined by hyphens, at most 40 characters, "workflow" when nothing is left. */
export function suggestName(title) {
  const words = String(title || "").toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  const cut = words.slice(0, NAME_MAX).replace(/-+$/g, "");
  return cut || "workflow";
}

/**
 * options: {api (flowSave), project, item (the resolved plan decision: id, title, resolution), can(op), signal, onSaved(result) (optional)}.
 * Returns the element, or null when the page may not save a workflow (the policy withholds `flow-save`) or the decision is not an approved plan.
 */
export function createSaveFlow({ api, project, item, can = () => true, signal, onSaved = null }) {
  if (!item || item.kind !== "plan" || item.resolution !== "approved" || !can("flow-save") || typeof api.flowSave !== "function") return null;
  counter += 1;
  const id = `wb-save-flow-${counter}`;
  const input = h("input", { class: "pui-input wb-lobby-field wb-field-input", id: `${id}-name`, type: "text", autocomplete: "off", spellcheck: "false", maxlength: String(NAME_MAX) });
  input.value = suggestName(item.title);
  const hint = h("small", { class: "wb-card-hint wb-hint", id: `${id}-hint`, text: "Lowercase words joined by hyphens. The workflow is saved in the project, in docs/workbench/flows/, where you version it." });
  input.setAttribute("aria-describedby", `${id}-hint`);
  const save = h("button", { class: "pui-btn pui-surface pui-outline wb-small-button wb-save-flow-button", type: "button", text: "Save workflow" });
  const split = h("button", { class: "pui-btn pui-surface pui-outline wb-small-button wb-save-flow-split", type: "button", hidden: true, text: "Save it with the split made by code" });
  const error = h("div", { class: "notice pui-soft pui-error wb-card-error", role: "alert", hidden: true });
  const done = h("p", { class: "wb-card-line", role: "status", hidden: true });
  const el = h("details", { class: "wb-disclosure wb-save-flow" },
    h("summary", { class: "wb-summary", text: "Save this plan as a workflow" }),
    h("div", { class: "wb-card-body" },
      h("label", { class: "pui-field-group wb-field", for: `${id}-name` }, h("span", { text: "Name of the workflow" }), input), hint,
      error, done, h("div", { class: "wb-card-actions" }, save, split)));
  let busy = false;

  function lock(on) {
    busy = on;
    for (const control of [input, save, split]) control.disabled = on;
    if (on) save.setAttribute("aria-busy", "true");
    else save.removeAttribute("aria-busy");
  }

  async function send(withSplit) {
    if (busy) return;
    const name = input.value.trim();
    error.hidden = true;
    done.hidden = true;
    if (!NAME.test(name) || name.length > NAME_MAX) {
      error.textContent = "A workflow's name is lowercase words joined by hyphens, at most 40 characters.";
      error.hidden = false;
      input.setAttribute("aria-invalid", "true");
      input.focus();
      return;
    }
    input.removeAttribute("aria-invalid");
    lock(true);
    try {
      const result = await api.flowSave(project, { name, pendingId: item.id, split: withSplit || undefined, signal });
      done.textContent = `Saved as ${result.path}${result.split ? ", with the split made by code" : ""}. Choose it in New request to run it.`;
      done.hidden = false;
      split.hidden = true;
      if (onSaved) onSaved(result);
    } catch (e) {
      if (e && e.name === "AbortError") return;
      const text = failureText(e);
      error.textContent = text;
      error.hidden = false;
      split.hidden = !(e && e.status === 409 && OFFER.test(text));
    }
    lock(false);
  }

  save.addEventListener("click", () => send(false));
  split.addEventListener("click", () => send(true));
  return el;
}
