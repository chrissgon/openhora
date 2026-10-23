// The parameters of a flow in the "New request" form (package P6a): when the flow chosen declares parameters (flows: `params`), one field for
// each, under the Flow select. A text parameter is a line (its default is the placeholder: left empty it takes the default); a file parameter is a
// file chosen on this machine, which the caller hands over for the request (`stage-file`) before the request is routed, so the plan carries the file's
// hash. The module reports what was typed and chosen; it checks only what the service would refuse for a name, and the service checks again.

import { h } from "../dom.js";
import { fileRefusal } from "../floor/hand-file.js";

let counter = 0;

/** The fields of the chosen flow's parameters. Returns {el, show(flow), problem(), list(), files(), disable(on), reset()}. */
export function createParams() {
  const el = h("div", { class: "wb-params", hidden: true });
  let fields = [];
  let disabled = false;

  function draw(flow) {
    fields = [];
    const params = flow && Array.isArray(flow.params) ? flow.params.filter((p) => p && typeof p.name === "string") : [];
    el.hidden = params.length === 0;
    el.replaceChildren(...params.map((p) => {
      counter += 1;
      const id = `wb-param-${counter}`;
      const isFile = p.type === "file";
      const input = isFile ? h("input", { class: "pui-input wb-file", id, type: "file" })
        : h("input", { class: "pui-input wb-lobby-field wb-field-input", id, type: "text", autocomplete: "off" });
      input.disabled = disabled;
      const hint = h("small", { class: "wb-card-hint wb-hint", id: `${id}-hint`, text: isFile ? "A file of yours: it is handed over for this request, and the plan carries its hash." : (p.required ? "Required." : "Optional: the flow has a default.") });
      input.setAttribute("aria-describedby", `${id}-hint`);
      fields.push({ name: p.name, required: Boolean(p.required), file: isFile, input });
      return h("label", { class: "pui-field-group wb-field", for: id }, h("span", { text: p.description ? `${p.name}: ${p.description}` : p.name }), input, hint);
    }));
  }

  return {
    el,
    /** The flow entry the person chose (an item of `flows`), or null for the planning agent's own choice: its parameters are drawn. */
    show(flow) {
      draw(flow);
    },
    /** "" when the fields are complete, else the sentence of the first that is not: a required one left empty, a file the service would refuse. */
    problem() {
      for (const f of fields) {
        if (f.file) {
          const file = f.input.files && f.input.files[0];
          if (!file && f.required) return `${f.name}: choose a file.`;
          const refusal = file ? fileRefusal(file.name, file.size) : "";
          if (refusal) return `${f.name}: ${refusal}`;
        } else if (f.required && !f.input.value.trim()) {
          return `${f.name}: type a value.`;
        }
      }
      return "";
    },
    /** The text parameters that were filled, as "name=value" (the form of --param). */
    list() {
      return fields.filter((f) => !f.file && f.input.value.trim()).map((f) => `${f.name}=${f.input.value}`);
    },
    /** The files chosen: [{param, file}], each to be handed over for the request before it is routed. */
    files() {
      return fields.filter((f) => f.file && f.input.files && f.input.files[0]).map((f) => ({ param: f.name, file: f.input.files[0] }));
    },
    disable(on) {
      disabled = Boolean(on);
      for (const f of fields) f.input.disabled = disabled;
    },
    reset() {
      for (const f of fields) f.input.value = "";
    },
  };
}
