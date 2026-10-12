// The "New request" form (R-44): not a modal and not a disclosure, but a form inside the Conversation that takes the place of the thread and the composer.
// At its head a button `Back to the conversation` (an arrow and the words), then the title `New request`, then the four fields: a text area, the Flow select
// (the first option lets the planning agent route it, then one option per flow of `flows`, labelled by the flow's own title), an optional title and "After
// request" (R-46: a select of the requests that are not final, A-29: the request waits for that one), and `Create request`, the form's one solid button.
// It reports what was typed and chosen; that the request is sent without a flow and routed in a second call is the caller's (lobby-actions.js). Hidden by
// default; Back (the button, or Escape with no field focused, which the frame turns into a click on it) tells the caller, and the draft stays in the fields.

import { h } from "../dom.js";
import { icon } from "../frame/icons.js";
import { AFTER_FORM_HINT, AUTO_FLOW, FORM_HINT, afterOptions, flowOptions } from "./lobby-model.js";

/** Create the form. options: {onCreate({text, flow, title, after?}), onBack()}. Returns {el, setFlows(list), setRequests(list), set(partial), markEmpty(), reset(), open(on), isOpen(), focus()}. */
export function createForm({ onCreate, onBack = () => {} }) {
  const textId = "wb-new-text";
  const flowId = "wb-new-flow";
  const titleId = "wb-new-title";
  const afterId = "wb-new-after";
  const text = h("textarea", { class: "pui-input wb-lobby-field wb-field-input", id: textId, rows: "3", autocomplete: "off" });
  const flow = h("select", { class: "pui-input wb-lobby-field wb-select", id: flowId }, h("option", { value: "", text: AUTO_FLOW }));
  const title = h("input", { class: "pui-input wb-lobby-field wb-field-input", id: titleId, type: "text", autocomplete: "off" });
  const after = h("select", { class: "pui-input wb-lobby-field wb-select", id: afterId, "aria-describedby": `${afterId}-hint` }, afterOptions([]).map((o) => h("option", { value: o.value, text: o.label })));
  const create = h("button", { class: "pui-btn pui-solid pui-theme", type: "submit", text: "Create request" });
  const error = h("div", { class: "notice pui-soft pui-error wb-card-error", role: "alert", hidden: true });
  const busy = h("div", { class: "wb-lobby-busy", role: "status", hidden: true }, h("span", { class: "wb-lobby-ring", "aria-hidden": "true" }), h("span", { text: "Creating the request..." }));
  const back = h("button", { class: "pui-btn pui-surface pui-outline wb-small-button wb-newreq-back", type: "button" }, icon("chevron-left", 16), h("span", { text: "Back to the conversation" }));
  back.addEventListener("click", () => onBack());
  const body = h("form", { class: "wb-form-body" },
    h("label", { class: "pui-field-group wb-field", for: textId }, h("span", { text: "What do you want done?" }), text),
    h("label", { class: "pui-field-group wb-field", for: flowId }, h("span", { text: "Flow" }), flow),
    h("label", { class: "pui-field-group wb-field", for: titleId }, h("span", { text: "Title (optional)" }), title),
    h("label", { class: "pui-field-group wb-field", for: afterId }, h("span", { text: "After request (optional)" }), after),
    h("small", { class: "wb-card-hint wb-hint", id: `${afterId}-hint`, text: AFTER_FORM_HINT }),
    error, busy,
    h("small", { class: "wb-card-hint wb-form-hint", text: FORM_HINT }),
    h("div", { class: "wb-newreq-buttons" }, create));
  const el = h("div", { class: "wb-newreq wb-new-request", hidden: true }, h("div", { class: "wb-newreq-head" }, back), h("strong", { class: "wb-newreq-title", text: "New request" }), body);
  let creating = false;
  let state = { creating: false, error: "", disabled: false };
  let offered = "";      // the options of "After request" now drawn, as one string

  body.addEventListener("submit", (event) => {
    event.preventDefault();
    if (creating) return;
    onCreate({ text: text.value, flow: flow.value, title: title.value, ...(after.value ? { after: after.value } : {}) });
  });

  return {
    el,
    /** The flows the service listed: the options after the first. A list that failed to load leaves the first alone. */
    setFlows(list) {
      const keep = flow.value;
      flow.replaceChildren(...flowOptions(list).map((o) => h("option", { value: o.value, text: o.label })));
      flow.value = [...flow.options].some((o) => o.value === keep) ? keep : "";
    },
    /** The requests of the project (`status.requests`): the options of "After request"; the choice stays while that request is still offered, else it is None. */
    setRequests(list) {
      const options = afterOptions(list);
      const key = options.map((o) => `${o.value}|${o.label}`).join("\n");
      if (key === offered) return;
      offered = key;
      const keep = after.value;
      after.replaceChildren(...options.map((o) => h("option", { value: o.value, text: o.label })));
      after.value = options.some((o) => o.value === keep) ? keep : "";
    },
    /** Merge a state into the form's: {creating, error, disabled}; a key left out keeps its value. */
    set(partial) {
      state = { ...state, ...partial };
      creating = Boolean(state.creating);
      for (const control of [text, flow, title, after, create]) control.disabled = creating || Boolean(state.disabled);
      create.textContent = creating ? "Creating..." : "Create request";
      if (creating) create.setAttribute("aria-busy", "true");
      else create.removeAttribute("aria-busy");
      busy.hidden = !creating;
      error.textContent = state.error || "";
      error.hidden = !state.error;
      if (creating) text.removeAttribute("aria-invalid");
    },
    /** Empty text is not sent: the field says so (aria-invalid) and takes the focus. */
    markEmpty() {
      text.setAttribute("aria-invalid", "true");
      text.focus();
    },
    reset() {
      text.value = "";
      title.value = "";
      after.value = "";
      flow.value = "";
    },
    /** Show or hide the form (the screen swaps it with the thread and the composer). */
    open(on) {
      el.hidden = !on;
    },
    isOpen() {
      return !el.hidden;
    },
    focus() {
      text.focus();
    },
  };
}
