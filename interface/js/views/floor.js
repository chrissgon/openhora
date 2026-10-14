// The Floor screen (handoff floor.md and cards.md, round 4): one agent in its room (the owl at its desk, the board of notes with its label, the bookcase: the three ways in, R-31) and a
// side panel with four tabs, in this order (R-33): Agent (state, mode, meters, the current task and its runs, other tasks, "Hand a file over"), Inbox (one card per open decision of the
// agent, then the resolved ones as a timeline), Tasks (every task of the agent by state, floor/tasks-tab.js) and Desk (the agent's documents and the viewer). It owns the scene engine
// for as long as the screen is shown. The page decides nothing:
// every panel shows what an operation returned, and each control sends one request (the cards, the Agent tab). This module
// reads (the status and agents the page already holds, a task's body, the documents) and arranges.

import * as api from "../api.js";
import { fill, h } from "../dom.js";
import * as fm from "../floor-model.js";
import { createAgentTab } from "../floor/agent-tab.js";
import { actions } from "../floor/actions.js";
import { createDeskTab } from "../floor/desk-tab.js";
import { createInbox } from "../floor/inbox.js";
import { createOwlList } from "../floor/owl-list.js";
import { createTasksTab } from "../floor/tasks-tab.js";
import { createViewer } from "../floor/viewer.js";
import { busyLine, createTabs, focusOpenLink } from "../floor/widgets.js";
import { PHONE_QUERY, bindDrawer, createGrip } from "../frame/drawer.js";
import { icon } from "../frame/icons.js";
import * as origin from "../frame/origin.js";
import { acceptance } from "../model.js";
import { can as pageMay } from "../permissions.js";
import * as router from "../router.js";
import { openOwl } from "../owl-words.js";
import { NoWebGL } from "../scene/engine.js";
import { bindSwipe } from "../swipe.js";
import { worldModel } from "../world-model.js";

const TASK_FRESH_MS = 5000;
const TASK_STALE_MS = 15000;
const DOCS_OPEN_MS = 5000;
const DOCS_IDLE_MS = 30000;
const MAX_TASK_READS = 12;
const TABS = [{ id: "agent", label: "Agent" }, { id: "inbox", label: "Inbox" }, { id: "tasks", label: "Tasks" }, { id: "desk", label: "Desk" }];     // R-33, C-6

/** Create the Floor in `frame`. env: {refresh()}. Returns {update({snapshot, route, now, reload}), dispose(), stats()}. */
export function createFloorView(frame, env) {
  let engine = null;
  let disposed = false;
  let last = null;
  let project = null;
  let agent = null;
  let documents = null;
  let documentsAt = 0;
  let documentsError = null;
  let readingDocuments = false;
  const bodies = new Map();       // task id -> {body, state, at}
  const reading = new Set();
  let shownScene = "";
  let viewerPath = null;
  let leftInbox = true;
  let wasWorking = null;       // the live region says when the agent starts working, never on the first read
  let reloaded = null;         // the page's reload stamp last seen: when it moves the store changed, and everything shown is read again
  let changes = 0;             // how many times it moved: a read that began before the last move is not fresh when it ends

  // --- the panel ---------------------------------------------------------------------------------------------------------------
  const tile = h("span", { class: "wb-kpi-tile pui-soft pui-warn" });
  const title = h("strong", { class: "wb-panel-title", id: "wb-floor-title", text: "" });
  const sub = h("span", { class: "wb-panel-sub", text: "" });
  const head = h("div", { class: "wb-panel-head wb-floor-head" }, tile, h("div", { class: "wb-panel-titles" }, title, sub));     // R-33: no line under it; M-12: no mode chip in the head on any tab or width (the mode is the Agent tab's)
  const tabs = createTabs("Floor", TABS, (id) => { window.location.hash = router.floorHash(project, agent, id); });
  const tabbar = h("div", { class: "wb-tabbar" }, tabs.el);
  const tabpanel = h("div", { class: "wb-panel-body wb-tabpanel", id: "wb-tabpanel", role: "tabpanel" });
  const normal = h("div", { class: "wb-floor-normal" }, head, tabbar, tabpanel);
  let shownTab = "agent";      // the tab on show: a swipe on the panel on a phone goes to the one beside it (A-77)
  const swipe = bindSwipe(tabpanel, {
    ids: () => TABS.map((t) => t.id), current: () => shownTab, enabled: () => viewerPath === null && Boolean(project),
    go: (id) => { window.location.hash = router.floorHash(project, agent, id); },
  });
  const backLink = h("a", { class: "pui-link pui-theme", href: router.cityHash(), text: "Back to the building" });   // the project is not known until the first update, which sets the Building's hash
  // floor.html: the panel of an agent that is not in the configuration still has its head, the name alone with the line under it
  const unknownTitle = h("strong", { class: "wb-unknown-title", text: "" });
  const unknown = h("div", { class: "wb-floor-unknown", hidden: true },
    h("div", { class: "wb-panel-head" }, h("div", { class: "wb-panel-titles" }, unknownTitle)),
    h("div", { class: "wb-panel-body" }, h("p", { text: "This agent is not in the project's configuration." }), backLink));
  const waitingEl = h("p", { class: "wb-empty-line", text: "Waiting for the configuration to be accepted." });
  const viewer = createViewer({
    onClose: () => closeViewer(),
    listed: (path) => (documents ? documents.rows.find((d) => d.path === path) : undefined),      // the Desk's list says what a file is (A-33)
  });
  // "Close" and a phone's dialog go to the one hash the frame's key handler also uses: the tab the document was opened from (frame/origin.js)
  function closeViewer() {
    if (last) origin.close(last.route);
  }
  const viewerHost = h("div", { class: "wb-viewer-host", hidden: true }, viewer.el);
  const grip = createGrip();
  const panel = h("section", { class: "pui-card wb-panel wb-drawer wb-panel-floor", role: "region", "aria-labelledby": "wb-floor-title", id: "wb-panel", tabindex: "-1" }, grip, normal, unknown, viewerHost);
  const drawer = bindDrawer(panel, { screen: "floor", grip });
  // the owls of the room, each selected on its own (PAR-7e): what the world last gave for them, and their twin list for the keyboard
  let owls = [];
  const owlList = createOwlList({
    hashOf: (target) => router.floorHash(project, agent, target.route.tab, target.route.id),
    highlight: (id, source) => { if (engine) engine.highlight(id, source); },
  });
  frame.main.append(panel, owlList.el);
  const phoneDialog = h("dialog", { class: "pui-modal wb-viewer-dialog", "aria-label": "Document" });
  phoneDialog.addEventListener("close", () => {
    if (viewerPath !== null && last && last.route.path) closeViewer();
  });
  frame.el.append(phoneDialog);
  const phone = window.matchMedia(PHONE_QUERY);     // M-3: the phone layout (the frame owns the width)

  // What the page may do in this project (js/permissions.js), read from the project's entry in the current snapshot at every draw: the tabs and the cards ask this getter
  const may = (op, kind) => pageMay(last && last.snapshot ? (last.snapshot.projects || []).find((p) => p.id === project) : null, op, kind);

  // the tab components need the project and the agent, known at the first update: they are made then
  let inbox = null;
  let desk = null;
  let agentTabLive = null;
  let tasksTab = null;

  function makeTabs() {
    if (inbox) return;
    agentTabLive = createAgentTab({
      project, agent, api: actions, refresh: () => env.refresh(), now: () => new Date(),
      links: { inbox: (id) => router.floorHash(project, agent, "inbox", id) }, task: (id) => api.task(project, id), can: may,
    });
    inbox = createInbox({
      project, now: () => new Date(), api: actions, can: may, refresh: () => { env.refresh(); readBodies(true); },
      links: {
        floor: (a) => router.floorHash(project, a), lobby: () => router.lobbyHash(project), parent: () => router.buildingHash(project),
        open: (item, path) => (item.agent ? router.deskHash(project, item.agent, path) : `${router.lobbyHash(project, "desk")}/${encodeURIComponent(path)}`),
      },
    });
    desk = createDeskTab({ project, agent, open: (path) => { window.location.hash = router.deskHash(project, agent, path); } });
    tasksTab = createTasksTab({
      project, now: () => new Date(), refresh: () => env.refresh(), api: actions, can: may,
      links: { request: () => router.lobbyHash(project), inbox: (id) => router.floorHash(project, agent, "inbox", id), open: (path) => router.deskHash(project, agent, path) },
    });
  }

  // --- the scene ---------------------------------------------------------------------------------------------------------------
  function sceneOpen(id) {
    if (disposed || !project) return;
    // one object per destination (R-23b, R-31): the tray the Inbox, the bookcase the Desk tab, the board the Tasks tab, the owl the Agent tab, a sheet its document
    if (id === "tasks") window.location.hash = router.floorHash(project, agent, "tasks");
    else if (id === "tray") window.location.hash = router.floorHash(project, agent, "inbox");
    else if (id === "desk") window.location.hash = router.floorHash(project, agent, "desk");
    else if (id === "agent") window.location.hash = router.floorHash(project, agent, "agent");
    else if (openOwl(owls, id, (tab, n) => { window.location.hash = router.floorHash(project, agent, tab, n); })) return;      // an owl of a task, or of a free place: its task, its decision or the Agent tab
    else if (String(id).startsWith("sheet:")) window.location.hash = router.deskHash(project, agent, String(id).slice(6));
  }

  try {
    engine = frame.acquireWorld({
      label: "Floor, loading",
      getInsets: () => {
        const base = frame.insets(panel);
        return base;     // on a phone the frame's insets already leave what the sheet and the cards cover
      },
      onOpen: sceneOpen,
      onUnavailable: () => frame.sceneUnavailable(true),
      onRestored: () => frame.sceneUnavailable(false),   // the context came back: the host is shown again
    });
    frame.sceneUnavailable(false);
  } catch (e) {
    if (!(e instanceof NoWebGL)) throw e;
    frame.sceneUnavailable(true);
  }
  const observer = new ResizeObserver(() => { if (engine) engine.refit(); });
  observer.observe(frame.track.el);
  observer.observe(panel);
  observer.observe(frame.noticeBox);

  // --- reading -----------------------------------------------------------------------------------------------------------------
  function ensureBody(task, maxAge) {
    const cached = bodies.get(task.id);
    if (reading.has(task.id)) return;
    if (cached && cached.state === task.state && Date.now() - cached.at < maxAge) return;
    reading.add(task.id);
    const began = changes;
    const stamped = () => (began === changes ? Date.now() : 0);     // 0: stale, read again at once
    api.task(project, task.id).then((body) => {
      bodies.set(task.id, { body, state: task.state, at: stamped() });
    }).catch(() => {
      bodies.set(task.id, { body: cached ? cached.body : null, state: task.state, at: stamped() });
    }).finally(() => {
      reading.delete(task.id);
      if (began !== changes) readBodies();
      redraw();
    });
  }

  function readBodies(force = false) {
    if (!last || !project) return;
    const view = fm.floor(last.snapshot, project, agent, bodiesPlain());
    if (!view || !view.found || view.notAccepted || view.unaccepted) return;     // not accepted: the bodies read before stay, nothing is asked of a refusing project
    const wanted = new Map();
    if (view.current) wanted.set(view.current.id, view.current);
    for (const t of view.runningTasks) wanted.set(t.id, t);      // every running task of the floor has its card: its runs are read
    if (last.route.tab === "inbox") for (const t of view.tasks.slice(0, MAX_TASK_READS)) wanted.set(t.id, t);
    for (const t of wanted.values()) {
      if (force) bodies.delete(t.id);
      ensureBody(t, t.state === "running" ? TASK_FRESH_MS : TASK_STALE_MS);
    }
  }

  function bodiesPlain() {
    const out = {};
    for (const [id, entry] of bodies) if (entry.body) out[id] = entry.body;
    return out;
  }

  async function readDocuments() {
    if (readingDocuments || disposed || !project) return;
    readingDocuments = true;
    try {
      const body = await api.artifacts(project);
      documents = { rows: Array.isArray(body.artifacts) ? body.artifacts : [], truncated: Boolean(body.truncated) };
      documentsError = null;
    } catch (e) {
      if (e && e.name === "ApiError" && e.status === 412) {
        // not accepted: the page shows its waiting line
      } else {
        documentsError = (e && e.message) || "The documents could not be read.";
      }
      if (!documents) documents = null;
    }
    documentsAt = Date.now();
    readingDocuments = false;
    redraw();
  }

  // --- drawing -----------------------------------------------------------------------------------------------------------------
  function drawHeader(model, tab) {
    const header = model.header;
    title.textContent = header.title;
    sub.textContent = header.sub;
    fill(tile, icon(header.icon, 16));
    const warn = model.row && model.row.state === "waiting";
    tile.className = `wb-kpi-tile pui-soft pui-${warn ? "warn" : "theme"}`;
  }

  function redraw() {
    if (disposed || !last) return;
    const { snapshot, route } = last;
    makeTabs();
    const loading = !snapshot.loaded;
    const model = loading ? null : fm.floor(snapshot, project, agent, bodiesPlain());
    const tab = TABS.some((t) => t.id === route.tab) ? route.tab : "agent";
    shownTab = tab;
    const missing = !loading && model && !model.found;
    unknown.hidden = !missing;
    normal.hidden = Boolean(missing);
    if (missing) {
      panel.removeAttribute("aria-labelledby");
      panel.setAttribute("aria-label", "Agent not found");
    } else {
      panel.removeAttribute("aria-label");
      panel.setAttribute("aria-labelledby", "wb-floor-title");
    }
    if (missing) {
      backLink.setAttribute("href", router.buildingHash(project));
      unknownTitle.textContent = agent ? `${agent.charAt(0).toUpperCase()}${agent.slice(1)}` : "";     // floor.html: the name alone
      title.textContent = unknownTitle.textContent;
      sub.textContent = "";
      fill(tile);
      tile.hidden = true;
      showScene(null, "Floor, agent not in the configuration", false);
      return;
    }
    tile.hidden = false;
    if (loading || !model) {
      fill(tile, icon("building-2", 16));
      title.textContent = format_title(agent);
      sub.textContent = "Loading the floor...";
      tabs.set(tab, {}, {});
      fill(tabpanel, busyLine("Loading the floor..."));
      showScene(null, "Floor, loading", false);
      return;
    }

    if (model.row && !model.notAccepted) {
      if (wasWorking === false && model.row.state === "working") frame.announce(`${model.row.label} agent started working`);
      wasWorking = model.row.state === "working";
    }
    drawHeader(model, tab);
    const documentsRows = documents ? fm.agentDocuments(documents.rows, agent, model.view.none) : [];
    const names = fm.tabNames(model.decisions.length, documentsRows.length);
    tabs.set(tab, { inbox: { count: model.decisions.length, tone: "pui-warn pui-soft" }, desk: { count: documentsRows.length, tone: "pui-muted pui-soft" } }, names);
    tabpanel.setAttribute("aria-labelledby", `wb-tab-${tab}`);

    const viewing = Boolean(route.path) && tab === "desk" && !model.notAccepted;
    drawViewer(route, viewing);
    const selected = model.notAccepted && tab !== "agent" ? { el: waitingEl } : { agent: agentTabLive, inbox, desk, tasks: tasksTab }[tab];
    if (tabpanel.children[0] !== selected.el) fill(tabpanel, selected.el);
    if (tab !== "inbox" && !leftInbox && !inbox.busy()) {   // a card whose job still runs keeps its state until it ends
      inbox.reset();
      leftInbox = true;
    }
    if (tab === "inbox") leftInbox = false;
    if (tab !== "tasks") tasksTab.forget();      // an owl's click names a task (PAR-7e): the next click on the same owl opens it again

    // A-16: while the configuration is not accepted the cards and the tasks' buttons are inert (they would only be refused)
    for (const part of [inbox, tasksTab]) {
      if (model.unaccepted) part.el.setAttribute("inert", "");
      else part.el.removeAttribute("inert");
    }

    if (tab === "agent") agentTabLive.update(model);
    else if (model.notAccepted) {
      // the waiting line is already in place
    } else if (tab === "inbox") {
      const ids = model.tasks.map((t) => t.id);
      inbox.update({ decisions: model.decisions, requests: snapshot.details[project].status.requests || [], resolved: fm.resolvedLines(bodiesPlain(), ids, last.now), selected: route.pending, loading: false });
    } else if (tab === "tasks") {
      const status = snapshot.details[project].status;
      tasksTab.update({ tasks: model.tasks, requests: status.requests || [], pending: status.pending || [], loading: false, reload: last.reload, unaccepted: model.unaccepted, selected: route.pending });
    } else {
      desk.update({ documents: documentsRows, truncated: Boolean(documents && documents.truncated), loading: documents === null && !documentsError, error: documentsError, elsewhere: documents ? documents.rows.length - documentsRows.length : 0 });
    }
    if (tab !== "agent") agentTabLive.update(model);   // keep the mode result notice and the state current while another tab is open

    const documentsFor = model.notAccepted ? [] : documentsRows;
    const scene = fm.roomScene(model, documentsFor, true, last.now);
    showScene({ tips: scene.tips, board: scene.board, door: false }, model.canvasLabel, true);
  }

  /** The title while the floor loads (floor.html: `Engineering agent`, as the loaded head says it). */
  function format_title(name) {
    return name ? `${name.charAt(0).toUpperCase()}${name.slice(1)} agent` : "";
  }

  // The scene is the world with this agent's floor as the target: the building stays open, the other floors are gone, the camera is on the room.
  function showScene(room, label, onFloor) {
    if (!last) return;
    const world = worldModel(last.snapshot, last.now, { selectedId: project, focus: project, floor: onFloor ? agent : null, room, documents: documents ? documents.rows : null, ready: true });
    owls = world.room && Array.isArray(world.room.owls) ? world.room.owls : [];
    owlList.update(owls);
    if (!engine) return;
    const key = JSON.stringify([world, label]);
    if (key === shownScene) return;
    shownScene = key;
    engine.show("world", world, label);
  }

  function drawViewer(route, viewing) {
    const isPhone = phone.matches;
    if (!viewing) {
      if (viewerPath !== null) {
        viewer.close();
        const back = viewerPath;
        viewerPath = null;
        if (phoneDialog.open) phoneDialog.close();
        // the focus goes back to what opened the document: its row on the Desk, or the "Open" link in the Inbox or in another tab
        if (route.tab === "inbox" && inbox) inbox.focusOpen(back);
        else if (route.tab === "desk" && desk) setTimeout(() => desk.focusRow(back), 0);
        else focusOpenLink(tabpanel, back);
      }
      viewerHost.hidden = true;
      return;
    }
    if (viewerPath !== route.path) {
      viewerPath = route.path;
      viewer.load(project, route.path).then(() => viewer.focus());
    }
    if (isPhone) {
      if (viewer.el.parentNode !== phoneDialog) phoneDialog.append(viewer.el);
      if (!phoneDialog.open) phoneDialog.showModal();
      viewerHost.hidden = true;
    } else {
      if (viewer.el.parentNode !== viewerHost) viewerHost.append(viewer.el);
      viewerHost.hidden = false;
      normal.hidden = true;
    }
  }

  return {
    /** data: {snapshot, route, now}. */
    update(data) {
      last = data;
      project = data.route.project;
      agent = data.route.agent;
      const listed = (data.snapshot.projects || []).find((p) => p.id === project);
      const kept = Boolean(listed) && acceptance(listed, data.snapshot.details[project]).kept;
      origin.track(data.route);
      if (reloaded !== null && data.reload !== reloaded) {     // the store changed: the bodies and the documents are stale, whatever their age
        changes += 1;
        for (const entry of bodies.values()) entry.at = 0;
        documentsAt = 0;
        if (agentTabLive) agentTabLive.reload();
        if (viewerPath !== null && !kept) viewer.load(project, viewerPath, { quiet: true });
      }
      reloaded = data.reload;
      if (data.snapshot.loaded) {
        readBodies();
        const stale = Date.now() - documentsAt > (data.route.tab === "desk" ? DOCS_OPEN_MS : DOCS_IDLE_MS);
        if ((documentsAt === 0 || stale) && !kept) readDocuments();     // a project that refuses (412) is not asked again on every reload
      }
      redraw();
    },
    dispose() {
      disposed = true;
      origin.reset();
      swipe.destroy();
      observer.disconnect();
      viewer.close();
      // the scene is the frame's: the Building takes it over (the floors come back), or the frame takes it down
      drawer.destroy();   // before the panel leaves the page: the frame hears that nothing covers the scene
      panel.remove();
      owlList.el.remove();
      phoneDialog.remove();
      frame.sceneUnavailable(false);
    },
    /** For the page's checks: the engine's counters, or null without WebGL. */
    stats() {
      return engine ? engine.stats() : null;
    },
    /** What a click on an object of the room opens (also what a test presses). */
    open(id) {
      sceneOpen(id);
    },
  };
}
