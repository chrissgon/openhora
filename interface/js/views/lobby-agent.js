// The Lobby's Agent tab (handoff lobby.md, "Agent tab"): the planning agent shown by the Floor's Agent tab (floor/agent-tab.js): the
// state row, the mode plate and "Set mode", the notices about the configuration, the meters, the current task, the other tasks and
// "Hand a file over". It is built from `agents`, `status`, and the bodies of the planning agent's tasks (`task`, read for the current
// and the running task, and for the first forty when the Inbox is open (P-6)), through the Floor's model with the
// planning agent allowed. Every control sends its request through floor/actions.js, handed to the tab.

import * as api from "../api.js";
import { h } from "../dom.js";
import * as fm from "../floor-model.js";
import { actions } from "../floor/actions.js";
import { createAgentTab } from "../floor/agent-tab.js";
import * as router from "../router.js";

const TASK_FRESH_MS = 5000;
const TASK_STALE_MS = 15000;
const MAX_TASK_READS = 40;     // P-6: with the Inbox open the planning agent's tasks are read for their resolved lines, the newest 40 (the Floor reads 12)
export const NO_AGENT_TEXT = "This project has no agents in its configuration.";

/**
 * Create the Agent tab. env: {project, now() (a Date), refresh() (read the screen's data again), changed() (a task was read)}.
 * Returns {el, update({snapshot, tab}) -> the Floor's model of the planning agent or null, bodies() -> {task id: body}, reload(), dispose()}.
 */
export function createLobbyAgent(env) {
  const { project } = env;
  const tab = createAgentTab({
    project, agent: fm.PLANNING, api: actions, refresh: env.refresh, now: env.now,
    links: { inbox: (id) => router.lobbyHash(project, "inbox", id) }, task: (id) => api.task(project, id),
  });
  const none = h("p", { class: "wb-empty-line wb-lobby-none", hidden: true, text: NO_AGENT_TEXT });
  const el = h("div", { class: "wb-lobby-agent" }, none, tab.el);
  const bodies = new Map();      // task id -> {body, state, at}
  const reading = new Set();
  let disposed = false;
  let changes = 0;               // how many times the store changed: a read that began before the last change is not fresh when it ends

  const plain = () => {
    const out = {};
    for (const [id, entry] of bodies) if (entry.body) out[id] = entry.body;
    return out;
  };

  function ensure(task, maxAge) {
    const cached = bodies.get(task.id);
    if (reading.has(task.id)) return;
    if (cached && cached.state === task.state && Date.now() - cached.at < maxAge) return;
    reading.add(task.id);
    const began = changes;
    const stamped = () => (began === changes ? Date.now() : 0);     // 0: stale, read again by the next update
    api.task(project, task.id).then((body) => {
      bodies.set(task.id, { body, state: task.state, at: stamped() });
    }).catch(() => {
      bodies.set(task.id, { body: cached ? cached.body : null, state: task.state, at: stamped() });
    }).finally(() => {
      reading.delete(task.id);
      if (!disposed) env.changed();
    });
  }

  function read(model, selected) {
    const wanted = new Map();
    if (model.current) wanted.set(model.current.id, model.current);
    const running = model.tasks.find((t) => t.state === "running");
    if (running) wanted.set(running.id, running);
    if (selected === "inbox") for (const t of model.tasks.slice(0, MAX_TASK_READS)) wanted.set(t.id, t);
    for (const t of wanted.values()) ensure(t, t.state === "running" ? TASK_FRESH_MS : TASK_STALE_MS);
  }

  return {
    el,
    /** Draw from the City's snapshot (js/data.js); tab: the selected tab id. Returns the model, or null while loading. */
    update({ snapshot, tab: selected }) {
      if (!snapshot.loaded) {
        tab.update(null);
        return null;
      }
      const model = fm.floor(snapshot, project, fm.PLANNING, plain(), { lobby: true });
      if (!model || !model.found) {
        tab.update(null);
        return null;
      }
      if (!model.notAccepted) read(model, selected);
      const empty = Boolean(model.view && model.view.none);
      none.hidden = !empty;
      tab.el.hidden = empty;
      tab.update(model);
      return model;
    },
    bodies: plain,
    /** The store changed: the bodies held are stale, whatever their age; the next update reads those it shows. */
    reload() {
      changes += 1;
      for (const entry of bodies.values()) entry.at = 0;
    },
    dispose() {
      disposed = true;
    },
  };
}
