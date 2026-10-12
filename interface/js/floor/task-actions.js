// The actions of one task, drawn the same way in the Tasks tab and in the Agent tab (A-32: one source). Which actions a state allows is
// tasks-model.actionsFor (Retry on failed or blocked, "Open in the Inbox" on waiting, "Go ahead" and "Drop the after" on a planned task that
// waits, A-29); this file turns them into nodes and sends them, each as one request through the client it is given (floor/actions.js):
// `retry`, `goAhead` (a task already created) and `goAhead` with `dropAfter`. A blocked task shows the sentence the runtime stored for it
// beside Retry (A-31), so the person does not retry the same stop. Every value is text.

import { h } from "../dom.js";
import { actionsFor, blockedNote } from "./tasks-model.js";
import { errorText, notice, ring } from "./widgets.js";

// kind -> [the button's word, its "-ing" word, the start of its accessible name]
const WORDS = Object.freeze({
  retry: ["Retry", "Retrying...", "Retry task"],
  "go-ahead": ["Go ahead", "Going ahead...", "Go ahead on task"],
  "drop-after": ["Drop the after", "Dropping...", "Drop the after of task"],
});
// What a go-ahead does, said beside the button (the runtime records the person's decision and asks nothing more).
export const GO_AHEAD_EFFECT = "The task starts without waiting; it may stop for the missing file.";

/**
 * Create the actions of a tab. env: {project, api: {retry, goAhead}, refresh() (read the page's data again), redraw() (the tab draws again),
 * done(id) (optional: an action succeeded, the tab drops what it held for the task)}.
 * Returns {nodes(task, {pending, links: {inbox(pendingId)}, locked}), failure(id), signature()}.
 */
export function createTaskActions(env) {
  const busy = new Set();       // "<kind>-<task id>" being sent
  const errors = new Map();     // task id -> the refusal's words

  async function press(kind, id) {
    const key = `${kind}-${id}`;
    if (busy.has(key)) return;
    busy.add(key);
    errors.delete(id);
    env.redraw();
    try {
      if (kind === "retry") await env.api.retry(env.project, id);
      else if (kind === "go-ahead") await env.api.goAhead(env.project, id);
      else await env.api.goAhead(env.project, id, { dropAfter: true });
      if (env.done) env.done(id);
    } catch (e) {
      errors.set(id, errorText(e));
    }
    busy.delete(key);
    env.redraw();
    env.refresh();
  }

  return {
    /** The action nodes of a task, in order, then the blocked sentence: [] when its state allows none. */
    nodes(task, { pending = [], links, locked = false } = {}) {
      const out = [];
      for (const action of actionsFor(task, pending)) {
        if (action.kind === "inbox") {
          out.push(h("a", { class: "pui-btn pui-surface pui-outline wb-small-button wb-task-inbox", href: links.inbox(action.pending), "data-key": `inbox-${task.id}`, text: "Open in the Inbox" }));
          continue;
        }
        const [word, doing, label] = WORDS[action.kind];
        const sending = busy.has(`${action.kind}-${task.id}`);
        const button = h("button", {
          class: `pui-btn pui-surface pui-outline wb-small-button wb-task-action wb-task-${action.kind}`, type: "button", "data-key": `${action.kind}-${task.id}`,
          "aria-label": `${label} ${task.id}`, "aria-busy": sending ? "true" : null,
        }, sending ? ring(true) : null, sending ? doing : word);
        button.disabled = sending || locked;
        button.addEventListener("click", () => press(action.kind, task.id));
        out.push(button);
      }
      if (out.some((n) => n.getAttribute && /go-ahead|drop-after/.test(n.getAttribute("data-key") || ""))) {
        out.push(h("span", { class: "wb-task-effect wb-muted", text: GO_AHEAD_EFFECT }));
      }
      const note = blockedNote(task);
      if (note && out.length) out.push(h("span", { class: "wb-task-note wb-muted wb-task-blocked-note", text: note }));
      return out;
    },
    /** The refusal of the last action on the task, as a notice, or null. */
    failure(id) {
      return errors.has(id) ? notice(errors.get(id), "error") : null;
    },
    /** What changes the nodes: a tab includes it in the signature of what it draws. */
    signature() {
      return [[...busy], [...errors]];
    },
  };
}
