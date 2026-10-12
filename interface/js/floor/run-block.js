// The run block both the Agent tab (the current task) and the Tasks tab (an expanded row) draw: one definition list of a run's
// facts, from floor-model.runRows. Every value is text; an unknown cost reads "unknown", never a number.

import { h } from "../dom.js";
import { runRows } from "../floor-model.js";
import { icon } from "../frame/icons.js";
import { splitRuns } from "./tasks-model.js";
import { chip } from "./widgets.js";

/** The `dl.wb-run` of a run (a row of `runs[]` of a task body). */
export function runBlock(run) {
  const rows = runRows(run);
  return h("dl", { class: "wb-run" }, rows.flatMap((r) => [
    h("dt", { class: "wb-muted", text: r.label }),
    h("dd", { class: r.kind === "code" || r.kind === "wrap" ? "mono" : null }, r.kind === "chip" ? chip(r.value, r.tone, "12") : r.value),
  ]));
}

/**
 * A-72, M-28: the runs of a task as the Tasks tab's opened row and the Agent tab's current-task card both draw them, one way in both places. `runs` is newest first. The run in
 * progress (else the last run) is "This run"; the earlier attempts, failed ones with their error, wait behind a closed "Earlier attempts (n)" disclosure so that an old failure
 * is not read as the state of the task; with one run there is no disclosure. `options`: {key (what names the disclosure's ids and its data-key, the task id), isOpen (the
 * person's choice, closed by default), onToggle() (the caller flips the choice and draws again)}. Returns an array of nodes; [] when there is no run.
 */
export function runsSection(runs, { key, isOpen = false, onToggle = () => {} }) {
  const { thisRun, earlier } = splitRuns(runs);
  if (!thisRun) return [];
  const parts = [h("span", { class: "wb-sec-head wb-runs-head", text: "This run" }), runBlock(thisRun)];
  if (earlier.length) {
    const listId = `wb-earlier-list-${key}`;
    const toggle = h("button", { class: "pui-btn pui-link wb-earlier-toggle wb-muted", type: "button", "data-key": `earlier-${key}`, "aria-expanded": isOpen ? "true" : "false", "aria-controls": listId, text: `Earlier attempts (${earlier.length})` },
      h("span", { class: "wb-earlier-mark", "aria-hidden": "true" }, icon("chevron-down", 14)));
    toggle.addEventListener("click", () => onToggle());
    parts.push(toggle, h("div", { class: "wb-earlier-list", id: listId, hidden: !isOpen }, isOpen ? earlier.map(runBlock) : null));
  }
  return parts;
}
