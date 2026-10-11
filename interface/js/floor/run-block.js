// The run block both the Agent tab (the current task) and the Tasks tab (an expanded row) draw: one definition list of a run's
// facts, from floor-model.runRows. Every value is text; an unknown cost reads "unknown", never a number.

import { h } from "../dom.js";
import { runRows } from "../floor-model.js";
import { chip } from "./widgets.js";

/** The `dl.wb-run` of a run (a row of `runs[]` of a task body). */
export function runBlock(run) {
  const rows = runRows(run);
  return h("dl", { class: "wb-run" }, rows.flatMap((r) => [
    h("dt", { class: "wb-muted", text: r.label }),
    h("dd", { class: r.kind === "code" || r.kind === "wrap" ? "mono" : null }, r.kind === "chip" ? chip(r.value, r.tone, "12") : r.value),
  ]));
}
