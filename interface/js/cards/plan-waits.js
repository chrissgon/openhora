// What a plan will wait for, shown before the person approves it (A-29): the pending decision's `payload.waits` ([{task_key, task_id, reason}]),
// `payload.missing` ([{task_key, skill, path, owner, sentence}], a required input nothing writes) and `payload.cycles` ([{task_key, sentence}]).
// Every task that waits for another task has a "Go ahead" checkbox; the keys of the boxes ticked travel with the approval (`go_ahead`, a list of
// task keys), so a derived wait is dropped only by the person's word. A wait for a request (`task_id` null: the "After request #n" the person set
// themselves) has no box: it is theirs, and the Tasks tab drops it later. Both plan cards (the Lobby's and the Floor's) draw this block, so it is
// one place. Every sentence is the runtime's own text; nothing is decided here.

import { h } from "../dom.js";

let counter = 0;

/** The entries of one list of the payload that are objects with a text task key. */
function entries(payload, name) {
  const list = payload && Array.isArray(payload[name]) ? payload[name] : [];
  return list.filter((e) => e && typeof e === "object" && typeof e.task_key === "string" && e.task_key);
}

/** The waits of a plan grouped by task key, in the order of the tasks: [{key, title, reasons, derived (a task is awaited), after (a request is awaited)}]. */
export function waitGroups(payload) {
  const tasks = payload && Array.isArray(payload.tasks) ? payload.tasks : [];
  const titles = new Map(tasks.map((t) => [t.key, (typeof t.title === "string" && t.title) || t.key]));
  const order = tasks.map((t) => t.key);
  const groups = new Map();
  for (const w of entries(payload, "waits")) {
    if (typeof w.reason !== "string" || !w.reason) continue;
    if (!groups.has(w.task_key)) groups.set(w.task_key, { key: w.task_key, title: titles.get(w.task_key) || w.task_key, reasons: [], derived: false, after: false });
    const group = groups.get(w.task_key);
    group.reasons.push(w.reason);
    if (w.task_id === null || w.task_id === undefined) group.after = true;
    else group.derived = true;
  }
  return [...groups.values()].sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));
}

/** Whether the payload holds anything to show. */
export function hasWaits(payload) {
  return entries(payload, "waits").length + entries(payload, "missing").length + entries(payload, "cycles").length > 0;
}

/**
 * The block. payload: the plan decision's. options: {disabled (the card is in flight), checked (a Set of task keys the card keeps between its draws:
 * the boxes start as it holds them and write back to it)}. Returns {el, keys(): the task keys ticked, setDisabled(on)},
 * or null when the plan waits for nothing and misses nothing.
 */
export function createWaitsBlock(payload, { disabled = false, checked = new Set() } = {}) {
  if (!hasWaits(payload)) return null;
  counter += 1;
  const uid = `wb-waits-${counter}`;
  const boxes = [];
  const parts = [h("strong", { class: "wb-waits-title", id: `${uid}-title`, text: "Before it starts" })];
  const groups = waitGroups(payload);
  if (groups.length) {
    parts.push(h("ul", { class: "wb-waits-list", "aria-labelledby": `${uid}-title` }, groups.map((g, i) => {
      const reasons = h("span", { class: "wb-waits-reasons wb-muted", text: g.reasons.join("; ") });
      if (!g.derived) return h("li", { class: "wb-waits-item" }, h("span", { class: "wb-waits-task", text: `${g.title} waits:` }), reasons);
      const box = h("input", { class: "wb-checkbox", type: "checkbox", id: `${uid}-box-${i}`, "data-key": `go-ahead-${g.key}`, "data-task-key": g.key });
      box.disabled = Boolean(disabled);
      box.checked = checked.has(g.key);
      box.addEventListener("change", () => {
        if (box.checked) checked.add(g.key);
        else checked.delete(g.key);
      });
      boxes.push(box);
      return h("li", { class: "wb-waits-item" },
        h("label", { class: "wb-waits-label", for: `${uid}-box-${i}` }, box, h("span", { class: "wb-waits-task", text: `Go ahead on ${g.title}` })),
        reasons);
    })));
  }
  const missing = entries(payload, "missing");
  if (missing.length) parts.push(h("ul", { class: "wb-waits-list is-missing" }, missing.map((m) => h("li", { class: "wb-waits-item", text: String(m.sentence || `${m.skill || ""} needs ${m.path || ""}`) }))));
  const cycles = entries(payload, "cycles");
  if (cycles.length) parts.push(h("ul", { class: "wb-waits-list is-cycles" }, cycles.map((c) => h("li", { class: "wb-waits-item", text: String(c.sentence || `${c.task_key} would wait in a circle`) }))));
  const el = h("div", { class: "wb-waits", role: "group", "aria-labelledby": `${uid}-title` }, parts,
    h("p", { class: "wb-card-note wb-muted", text: "Tick Go ahead to start a task without waiting for what is listed; a task you leave unticked waits." }));
  return {
    el,
    keys: () => boxes.filter((b) => b.checked).map((b) => b.getAttribute("data-task-key")),
    setDisabled(on) {
      for (const b of boxes) b.disabled = Boolean(on);
    },
  };
}
