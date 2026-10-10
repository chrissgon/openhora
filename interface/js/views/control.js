// The Control room screen (handoff control-room.md): a 700 px panel with three tabs, Skills, Costs and Connections, in the
// shared frame. It is read-only: the page makes the reads `skills`, `costs` (with `agents` for the caps line) and
// `connections` once on entering, once on return from a hidden tab, and `costs` again when the Since date changes. Each tab
// shows its own loading line until its read returns and its own notice when its read failed (OPEN-32). Nothing here writes.

import * as api from "../api.js";
import { h } from "../dom.js";
import { EVENT as DRAWER_EVENT } from "../frame/drawer.js";
import { createPanel } from "../frame/panel.js";
import { createEngine, NoWebGL } from "../scene/engine.js";
import * as router from "../router.js";
import { createConnectionsTab } from "./control-connections.js";
import { createCostsTab } from "./control-costs.js";
import * as model from "./control-model.js";
import { emptyBlock, loadingCard } from "./control-parts.js";
import "./control-scene.js";
import { createSkillsTab } from "./control-skills.js";

const AGE_MS = 30000;      // the Skills and Connections tabs are read again, on a change or on opening, when their data is this old

/** The text of a failure: the service's own message for a refusal, the client's sentence for a lost connection. */
export function messageOf(error) {
  return error && typeof error.message === "string" && error.message ? error.message : "The read failed.";
}

/**
 * Create the Control room in `frame`. Returns {el, update({loaded, known, accepted, projectId, projectName, tab}), dispose()}.
 * loaded: the page has read the project list once; known: the project exists; accepted: its configuration is accepted.
 */
export function createControlView(frame) {
  const panel = createPanel({ screen: "control", title: "Control room", subtitle: model.subtitleOf("skills", ""), icon: "server", width: "wide" });
  panel.el.classList.add("wb-control");
  const skills = createSkillsTab();
  const costs = createCostsTab({ onSince: (text) => readCosts(text) });
  const connections = createConnectionsTab();
  const tabs = new Map([["skills", skills], ["costs", costs], ["connections", connections]]);
  const waiting = h("div", { class: "wb-tab-body" });

  const buttons = new Map();
  const panels = new Map();
  const list = h("div", { class: "wb-tablist", role: "tablist", "aria-label": "Control room" });
  for (const [id, label] of model.TABS) {
    const button = h("button", { class: "pui-btn pui-surface pui-link wb-tab", type: "button", role: "tab", id: `wb-tab-${id}`, "aria-controls": `wb-tabpanel-${id}`, text: label });
    button.addEventListener("click", () => go(id));
    button.addEventListener("keydown", (event) => onTabKey(event, id));
    buttons.set(id, button);
    list.append(button);
    panels.set(id, h("div", { role: "tabpanel", id: `wb-tabpanel-${id}`, "aria-labelledby": `wb-tab-${id}`, hidden: true }, tabs.get(id).el));
  }
  const content = h("div", { class: "wb-control-content" }, ...panels.values(), waiting);
  panel.body.append(h("div", { class: "wb-control-body" }, list, content));
  frame.main.append(panel.el);

  // The small server-room scene: the racks are the Connections tab, the wall screen the Costs tab, the console the Skills tab.
  let engine = null;
  try {
    engine = createEngine(frame.sceneHost, {
      label: "Server room, loading",
      getInsets: () => frame.insets(panel.el),
      onOpen: (id) => go(model.OPENS[id] || "skills"),
      onUnavailable: () => frame.sceneUnavailable(true),
    });
    frame.sceneUnavailable(false);
  } catch (e) {
    if (!(e instanceof NoWebGL)) throw e;
    frame.sceneUnavailable(true);
  }
  // The Control room draws its own scene, not the frame's: a sheet at full on a phone pauses it, as a hidden tab does.
  panel.el.addEventListener(DRAWER_EVENT, (event) => { if (engine) engine.setPaused(Boolean(event.detail && event.detail.covering)); });
  // a panel or a band that changes size changes the free rectangle: one refit and one frame, never on a timer
  const observer = new ResizeObserver(() => { if (engine) engine.refit(); });
  observer.observe(panel.el);
  observer.observe(frame.noticeBox);

  let projectId = null;
  let projectName = "";
  let tab = "skills";
  let shown = "skills";     // the tab whose panel is on show, so that a newly chosen one starts at its top
  let disposed = false;
  let started = false;
  let reloaded = null;      // the page's reload stamp last seen: when it moves the store changed
  const readAt = { skills: 0, connections: 0 };   // when each of the two dear tabs was last read (ms): they are read again when the data is older than 30 s
  let message = null;       // what the content shows instead of the tabs: loading, or not accepted
  const aborter = new AbortController();
  const loads = { skills: { status: "loading" }, costs: { status: "loading", fieldValue: null, agents: null }, connections: { status: "loading" } };
  const generation = { skills: 0, costs: 0, connections: 0 };
  let sceneCosts = null;    // the costs read with the operation's own window: the wall screen's bars do not follow the Since field
  let lastSince;            // the date the Costs tab asked for last (undefined: the operation's own default)

  function show(id) {
    tabs.get(id).set(loads[id]);
    drawScene();
  }

  function drawScene() {
    if (!engine) return;
    const sceneModel = model.sceneModel({
      accepted: !(message && message.kind === "text"),
      connections: loads.connections.status === "ready" ? loads.connections.data : null,
      costs: sceneCosts,
      tab,
      failed: loads.connections.status === "failed",   // B3-5: a failed read keeps the open tab's object marked, as the page draws it
    });
    engine.show("server", sceneModel, sceneModel.label);
  }

  /** The line under the title follows the tab (E-10): the project's for Skills and Costs, the machine's for Connections. */
  function setSub() {
    const words = model.subtitleOf(tab, projectName);
    if (panel.sub.textContent !== words) panel.sub.textContent = words;
  }

  function select(id) {
    tab = id;
    setSub();
    for (const [name, button] of buttons) {
      const on = name === id;
      button.setAttribute("aria-selected", String(on));
      button.setAttribute("tabindex", on ? "0" : "-1");
      button.classList.toggle("is-selected", on);
      panels.get(name).hidden = !on || Boolean(message);
    }
    waiting.hidden = !message;
    if (id !== shown) content.scrollTop = 0;
    shown = id;
  }

  function go(id) {
    if (!projectId) return;
    window.location.hash = router.controlHash(projectId, id);
  }

  function onTabKey(event, id) {
    const ids = model.TABS.map(([name]) => name);
    const index = ids.indexOf(id);
    const next = { ArrowRight: ids[(index + 1) % ids.length], ArrowLeft: ids[(index + ids.length - 1) % ids.length], Home: ids[0], End: ids[ids.length - 1] }[event.key];
    if (!next) return;
    event.preventDefault();
    buttons.get(next).focus();
    go(next);
  }

  function fail(id, error) {
    if (disposed || (error && (error.name === "AbortError" || error.unauthorized))) return false;
    loads[id] = { ...loads[id], status: "failed", error: messageOf(error) };
    return true;
  }

  const aged = (id) => Date.now() - readAt[id] >= AGE_MS;

  async function readSkills() {
    const mine = ++generation.skills;
    try {
      const data = await api.skills(projectId, { signal: aborter.signal });
      if (disposed || mine !== generation.skills) return;
      loads.skills = { status: "ready", data };
      readAt.skills = Date.now();
    } catch (e) {
      if (mine !== generation.skills || !fail("skills", e)) return;
    }
    show("skills");
  }

  async function readConnections() {
    const mine = ++generation.connections;
    try {
      const data = await api.connections(projectId, { signal: aborter.signal });
      if (disposed || mine !== generation.connections) return;
      loads.connections = { status: "ready", data };
      readAt.connections = Date.now();
    } catch (e) {
      if (mine !== generation.connections || !fail("connections", e)) return;
    }
    show("connections");
  }

  /** since: the text the person typed, or undefined for the operation's default. The service is the one validator of a date. */
  async function readCosts(since, quiet = false) {
    const mine = ++generation.costs;
    lastSince = since;
    const before = loads.costs;
    // a read on return from a hidden tab does not blank a tab that has its data; a new date does show the loading line
    if (!quiet || before.status !== "ready") {
      loads.costs = { ...before, status: "loading", fieldValue: since === undefined ? before.fieldValue : since };
      show("costs");
    }
    try {
      // the caps line needs what was used today: `agents`; a failure of that read leaves the used amounts as "-"
      const [data, agents] = await Promise.all([
        api.costs(projectId, { since, signal: aborter.signal }),
        api.agents(projectId, { signal: aborter.signal }).then((body) => (Array.isArray(body.agents) ? body.agents : null), (e) => {
          if (e && (e.name === "AbortError" || e.unauthorized)) throw e;
          return null;
        }),
      ]);
      if (disposed || mine !== generation.costs) return;
      loads.costs = { status: "ready", data, agents, fieldValue: typeof data.since === "string" ? data.since : String(since ?? "") };
      if (since === undefined) sceneCosts = data;
    } catch (e) {
      if (disposed || mine !== generation.costs || (e && (e.name === "AbortError" || e.unauthorized))) return;
      const text = since === undefined ? loads.costs.fieldValue : since;
      if (e && e.name === "ApiError" && e.status === 400) {
        loads.costs = { status: "refused", error: messageOf(e), agents: null, fieldValue: text ?? "" };
      } else {
        loads.costs = { ...loads.costs, status: "failed", error: messageOf(e), fieldValue: text ?? null };
      }
    }
    show("costs");
  }

  function readAll() {
    readSkills();
    readCosts(lastSince, true);
    readConnections();
  }

  function render() {
    waiting.replaceChildren(...(message ? [message.kind === "loading" ? loadingCard(model.LOADING) : message.text ? emptyBlock(message.text) : null] : []).filter(Boolean));
    select(tab);
    drawScene();
  }

  select("skills");
  for (const id of tabs.keys()) show(id);

  return {
    el: panel.el,
    /** state: {loaded, known, accepted, projectId, tab, reload}; called on every render, so it only reconciles; when `reload` moves the store changed. */
    update(state) {
      projectId = state.projectId;
      projectName = typeof state.projectName === "string" ? state.projectName : "";
      const wanted = model.tabOf(state.tab);
      const changed = wanted !== tab;
      let next = null;
      if (!state.loaded) next = state.unread ? { kind: "none", text: "" } : { kind: "loading" };   // a failed first read: the frame's notice says why
      else if (!state.known) next = { kind: "none", text: "The service has no such project." };
      else if (!state.accepted && !(state.kept && started)) next = { kind: "text", text: model.NOT_ACCEPTED };     // not accepted after a read: the tabs stay, dimmed, and read nothing more (A-16)
      const same = (next === null && message === null) || (next && message && next.kind === message.kind && next.text === message.text);
      message = next;
      if (!same || changed) {
        tab = wanted;
        render();
      } else {
        setSub();   // the project's name may have arrived with this update
      }
      const moved = reloaded !== null && state.reload !== reloaded && state.accepted !== false;
      reloaded = state.reload;
      if (!message && !started) {
        started = true;
        readAll();
      } else if (!message && moved) {
        // The store changed. The costs are read again (they feed the room and are cheap). The Skills and Connections tabs are
        // about 0.8 s of server work each and a dispatcher writes every few seconds: the open one is read again only when its data
        // is older than 30 s (so the safety net's reload does it), and the other when it is opened.
        if (wanted === "skills" && aged("skills")) readSkills();
        else if (wanted === "connections" && aged("connections")) readConnections();
        readCosts(lastSince, true);
      } else if (!message && state.accepted !== false && changed && (wanted === "skills" || wanted === "connections") && aged(wanted)) {
        if (wanted === "skills") readSkills();
        else readConnections();
      } else if (!message && state.accepted !== false && changed && loads[wanted].status === "failed") {
        if (wanted === "skills") readSkills();
        else if (wanted === "connections") readConnections();
        else readCosts(lastSince, true);
      }
    },
    dispose() {
      disposed = true;
      aborter.abort();
      skills.dispose();
      observer.disconnect();
      if (engine) engine.dispose();
      frame.sceneUnavailable(false);
      panel.drawer.destroy();   // before the panel leaves the page
      panel.el.remove();
    },
  };
}
