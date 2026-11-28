// The Office screen (slice 1): one room that holds every agent of the project, drawn in 2D on a canvas, with the number of decisions waiting for the
// person first and a list of the same agents beside it (the list is the accessible twin of the picture). It only reads the snapshot the page already
// holds: no client call, nothing written. A click on a figure or a row goes to that agent's oldest open decision, or to its floor when it has none;
// the decision itself is answered on its own card, never here.

import { h } from "../dom.js";
import { cull, MAX_LABELS, rankOf } from "../scene/cull.js";
import { officeOf, fnv1a32 } from "../office/office-model.js";
import { PathFinder } from "../office/astar.js";
import { buildRoom, MAX_SEATS } from "../office/room.js";
import { createOfficeScene } from "../office/scene.js";
import { createWalkers, seeded, WANDER_MS } from "../office/walk.js";
import { word } from "../office/words.js";

const LABEL_H = 30;       // CSS pixels a label is tall, for the overlap test
const LABEL_CHAR = 7;     // CSS pixels a character of a label is wide, for the same test

/**
 * Create the Office in `frame` (only frame.sceneHost and frame.main are used). The options are the browser's own, given so that a test runs the view
 * with stand-ins. Returns {update({snapshot, route, now, reload}), dispose()}.
 */
export function createOfficeView(frame, {
  context = (canvas) => (canvas.getContext ? canvas.getContext("2d") : null),
  raf = (fn) => requestAnimationFrame(fn),
  caf = (id) => cancelAnimationFrame(id),
  hidden = () => document.hidden,
  reduced = () => Boolean(typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches),
  setTimer = (fn, ms) => setTimeout(fn, ms),
  clearTimer = (id) => clearTimeout(id),
  clock = () => Date.now(),
} = {}) {
  const title = h("h2", { id: "wb-office-title", text: word("office.title") });
  const count = h("p", { class: "wb-office-count", "aria-live": "polite", text: word("office.loading") });
  const note = h("p", { class: "wb-office-note wb-muted", hidden: true });
  const roomHeading = h("h3", { class: "wb-sec-head", text: word("office.room") });
  const list = h("ul", { class: "wb-office-list", "aria-label": word("office.list") });
  const panel = h("section", { class: "pui-card wb-panel wb-office-panel", role: "region", "aria-labelledby": "wb-office-title" }, title, count, note, roomHeading, list);
  const overlay = h("div", { class: "wb-office-labels" });
  frame.main.append(panel);
  frame.sceneHost.append(overlay);

  let disposed = false;
  let agents = [];
  let drawn = [];
  let names = "";
  let listKey = "";
  let room = null;
  let walkers = null;
  let random = seeded(0);
  let seed = null;
  let lastStamp = null;
  let timer = null;
  const labels = new Map();

  function open(name) {
    const agent = agents.find((a) => a.name === name);
    if (agent) window.location.hash = agent.link;
  }

  const scene = createOfficeScene(frame.sceneHost, {
    context, raf, caf, hidden, reduced, onPick: (name) => name && open(name),
    onFrame: (stamp) => {
      if (!walkers) return;
      const dt = lastStamp === null ? 0 : Math.min(100, Math.max(0, stamp - lastStamp));
      lastStamp = stamp;
      walkers.advance(dt, clock(), random);
      placeLabels();
      if (!walkers.moving() && scene) {
        scene.stopWalk();
        lastStamp = null;
      }
    },
  });

  const onVisibility = () => {
    if (scene) scene.setHidden(document.hidden);
    if (document.hidden) stopTimer();
    else armTimer();
  };
  document.addEventListener("visibilitychange", onVisibility);

  // An idle figure gets up from its seat now and then. The loop is stopped while nothing moves, so a timer wakes it; there is none under reduced motion.
  function armTimer() {
    if (timer !== null || disposed || !scene || reduced() || hidden() || !drawn.some((a) => a.state === "idle")) return;
    timer = setTimer(() => {
      timer = null;
      if (disposed || !walkers) return;
      if (!walkers.moving()) walkers.advance(WANDER_MS, clock(), random);
      if (walkers.moving()) wake();
      armTimer();
    }, WANDER_MS);
  }

  function stopTimer() {
    if (timer !== null) clearTimer(timer);
    timer = null;
  }

  function wake() {
    lastStamp = null;
    scene.startWalk();
  }

  function labelFor(agent) {
    let label = labels.get(agent.name);
    if (!label) {
      label = h("div", { class: "wb-label wb-office-label", "aria-hidden": "true" }, h("span", { class: "wb-label-name" }), h("span", { class: "wb-label-sub" }));
      labels.set(agent.name, label);
      overlay.append(label);
    }
    label.children[0].textContent = agent.display;
    label.children[1].textContent = word(`state.${agent.state}`);
    return label;
  }

  /** The labels of the figures, at most MAX_LABELS and none over another: a label that decisions wait on is kept first. */
  function placeLabels() {
    if (!scene || !walkers) return;
    const at = new Map(walkers.positions().map((f) => [f.name, f]));
    const items = [];
    for (const agent of drawn) {
      const figure = at.get(agent.name);
      if (!figure) continue;
      const point = scene.screenOf(figure);
      const width = (Math.max(agent.display.length, word(`state.${agent.state}`).length) + 2) * LABEL_CHAR;
      items.push({ id: agent.name, point, rank: rankOf({ selected: false, decisions: agent.decisions, running: agent.state === "working" }),
        rect: { left: point.x - width / 2, right: point.x + width / 2, top: point.y - LABEL_H, bottom: point.y } });
    }
    const kept = cull(items, { max: MAX_LABELS });
    for (const item of items) {
      const label = labelFor(agents.find((a) => a.name === item.id));
      label.hidden = !kept.has(item.id);
      label.style.setProperty("--wb-x", `${Math.round(item.point.x)}px`);
      label.style.setProperty("--wb-y", `${Math.round(item.point.y)}px`);
    }
  }

  function drawList(data) {
    const key = JSON.stringify(data.agents.map((a) => [a.name, a.state, a.decisions, a.link]));
    if (key === listKey) return;
    listKey = key;
    list.replaceChildren(...data.agents.map((agent) => {
      const state = word(`state.${agent.state}`);
      const row = h("a", { class: "wb-office-row", href: agent.link },
        h("span", { class: "wb-office-name", text: agent.display }),
        h("span", { class: "wb-office-state", text: state }),
        agent.decisions > 0 ? h("span", { class: "pui-badge pui-warn pui-soft", text: word("office.decisions", { n: agent.decisions }) }) : null);
      row.setAttribute("aria-label", `${word("office.figure", { vars: { name: agent.display, state } })}${agent.decisions > 0 ? `, ${word("office.decisions", { n: agent.decisions })}` : ""}`);
      return h("li", {}, row);
    }));
  }

  function drawNote(overflow) {
    const text = !scene ? word("office.fallback") : overflow > 0 ? word("office.overflow", { n: overflow }) : "";
    note.textContent = text;
    note.hidden = text === "";
  }

  return {
    /** data: {snapshot, route, now, reload}. */
    update(data) {
      if (disposed) return;
      const found = officeOf(data.snapshot, data.route.project, data.now);
      if (!found.ready) {
        count.textContent = word("office.loading");
        return;
      }
      count.textContent = word("office.waiting", { n: found.count });
      agents = found.agents;
      drawList(found);
      drawNote(Math.max(0, agents.length - MAX_SEATS));
      if (!scene) return;
      const nextNames = agents.map((a) => a.name).join("|");
      if (seed !== data.route.project) {
        seed = data.route.project;
        random = seeded(fnv1a32(seed));
      }
      const rebuilt = nextNames !== names || !room;
      if (rebuilt) {
        names = nextNames;
        room = buildRoom(agents.map((a) => a.name));
        walkers = createWalkers(room, new PathFinder(room.grid));
        for (const label of labels.values()) label.remove();
        labels.clear();
      }
      drawn = agents.slice(0, room.seats.length);
      walkers.retarget(drawn, { reduced: reduced() });
      scene.setModel(room, drawn, walkers);
      placeLabels();
      if (walkers.moving()) wake();
      armTimer();
    },
    dispose() {
      disposed = true;
      stopTimer();
      document.removeEventListener("visibilitychange", onVisibility);
      if (scene) scene.dispose();
      overlay.remove();
      panel.remove();
    },
  };
}
