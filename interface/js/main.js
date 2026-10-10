// The page: the token prompt, then the shared frame with the screen the hash names (#/city is the City, then the Building, the Floor, the
// Lobby and the Control room; a screen with no view falls back to the placeholder; #/ is the entry: the City, or the Building of the one
// project of a service that holds one, by a rule that runs once, on the first read of the projects). The page is kept current by a watcher (watch.js): while the
// document is visible it reads the service's change signal every second and, when a number moved (or after 30 quiet seconds, or after any
// write the page sent), reloads everything it shows; it reads nothing while the document is hidden and reloads once when it becomes visible.

import * as api from "./api.js";
import { emptySnapshot, refresh, versionKey } from "./data.js";
import { h } from "./dom.js";
import { createFrame } from "./frame/frame.js";
import { createProjectsPanel } from "./views/city-projects.js";
import { projectsOf, readableProject } from "./views/city-projects-model.js";
import { initMode } from "./mode.js";
import * as model from "./model.js";
import * as router from "./router.js";
import { clearToken, getToken, setToken } from "./token.js";
import { coalesce, createWatcher } from "./watch.js";
import { createBuildingView } from "./views/building.js";
import { createCityView } from "./views/city.js";
import { createControlView } from "./views/control.js";
import { createFloorView } from "./views/floor.js";
import { createLobbyView } from "./views/lobby.js";
import { createPlaceholder } from "./views/placeholder.js";
import { showTokenPrompt } from "./views/token-prompt.js";

const root = document.getElementById("app");
const NETWORK_TEXT = "The service could not be reached. Is it still running?";

let frame = null;
let tokenView = null;      // the token prompt on the page, or null
let view = null;           // {key, screen, update(...), dispose()}
let snapshot = emptySnapshot();
let selected = null;       // the project the tracking bar follows on the City (memory only)
let failure = null;        // the last failed read, or null
let generation = 0;        // a reload that was left behind (the document was hidden, the token asked for again) stops
let reloads = 0;           // the stamp every screen is given: it moves when a reload has read everything again
let watcher = null;
let drawnKey = null;
let knownDecisions = null; // ids of the decisions seen, to announce a new one
let pendingMessage = null;
let lastFollowed = null;   // the project the last poll read tasks for

function currentRoute() {
  return router.parse(window.location.hash);
}

function followed(route) {
  return route.project || selected;
}

function stopPolling() {
  generation += 1;
}

/** One full read of everything the page shows, drawn. A reload that was left behind by stopPolling() ends without drawing. */
async function poll() {
  const mine = ++generation;
  let key = null;
  try {
    key = await versionKey();        // the signal first, then the data: what is written after this read is read by the next one
    lastFollowed = followed(currentRoute());
    const next = await refresh(snapshot, lastFollowed, { force: true });
    if (mine !== generation || !frame) return;
    snapshot = next;
    failure = null;
    reloads += 1;
    chooseDefault();
    render();
  } catch (e) {
    if (mine !== generation || !frame) return;
    if (e && e.unauthorized) return;      // the client already sent the page back to the token prompt
    failure = e;
    render();
  }
  // A project that refused its read (not "not accepted", which stays until the terminal accepts it) is a reload that failed as well.
  const refused = Object.values(snapshot.details).some((d) => d && d.error && d.error.status !== 412);
  const ok = !failure && !refused;
  if (watcher) watcher.reloaded(ok ? key : null);      // a reload that failed read nothing: it rebases nothing
  return ok;                              // false: the page says what failed and the watcher reads again after 10 s
}

/** Reload, one at a time: a request made while one is running makes one more after it, and its caller waits for that one. */
const reload = coalesce(() => poll());
/** What a screen calls after its own write: the reload that write already asked for (api.onWrite), or one. */
const reloaded = () => reload.join("screen");

/** The project the tracking bar follows when none was chosen: the first with a request open, else the first. */
function chooseDefault() {
  const projects = snapshot.projects;
  if (selected && projects.some((p) => p.id === selected)) return;
  const withRequest = projects.find((p) => snapshot.details[p.id] && snapshot.details[p.id].status && model.openRequest(snapshot.details[p.id].status));
  selected = (withRequest || projects[0] || { id: null }).id;
}

function askForToken(message) {
  stopPolling();
  if (watcher) watcher.stop();
  watcher = null;
  if (view) view.dispose();
  view = null;
  if (frame) frame.destroy();
  frame = null;
  drawnKey = null;
  if (tokenView) tokenView.destroy();
  const holder = h("div", { class: "tk-root" });
  root.replaceChildren(holder);
  tokenView = showTokenPrompt(holder, {
    message: message || pendingMessage,
    tokenFile: () => api.tokenFile({ signal: typeof AbortSignal !== "undefined" && AbortSignal.timeout ? AbortSignal.timeout(4000) : undefined }),
    onSubmit: async (pasted) => {
      setToken(pasted);
      pendingMessage = null;
      start();
    },
  });
  pendingMessage = null;
}

// Any write the page sends is answered by a reload at once: it may have changed what every screen shows. (The fast poll of a job the
// write started is api.pollJob's, as before; the signal catches the job's own writes when it ends.)
api.onWrite(() => {
  if (frame) reload();
});

api.onAuthFailure(() => {
  clearToken();
  pendingMessage = "The token was not accepted. The service writes a new token every time it starts: read the token file again.";
  askForToken();
});

function start() {
  if (!getToken()) {
    askForToken();
    return;
  }
  if (tokenView) tokenView.destroy();
  tokenView = null;
  snapshot = emptySnapshot();
  model.resetRequestChoices();
  selected = null;
  failure = null;
  knownDecisions = null;
  // "Add a project..." and "Leave this project..." of the switcher's foot (A-35): the command panel the frame draws on every screen (it shows the lines,
  // the person types them in the terminal; the page opens nothing)
  const projectsPanel = createProjectsPanel({
    readStart: async () => {
      const id = readableProject(snapshot);
      if (id === null) return "";
      const got = await api.connections(id);
      return got && got.service && typeof got.service.start === "string" ? got.service.start : "";
    },
  });
  frame = createFrame(root, {
    projectsPanel,
    onSelectProject: selectProject,
    onSelectRequest: selectRequest,
    onForgetToken: () => {
      clearToken();
      askForToken();
    },
    onRetry: () => reload(),
  });
  drawnKey = null;
  render();
  // The signal is read first (the baseline), then everything: a write that lands in between is seen by the next read.
  watcher = createWatcher({
    read: versionKey, reload, hidden: () => document.hidden,
    setTimer: (fn, ms) => setTimeout(fn, ms), clearTimer: (id) => clearTimeout(id), now: () => Date.now(),
  });
  watcher.start().then(() => reload());
}

// A request chosen on the tracking bar or on a row of the Building's "Requests (n)" (R-27): the page follows it, kept in memory for the session
function selectRequest(project, id) {
  model.chooseRequest(project, id);
  render();
  reload();   // the running task's start time of the request now shown
}

function selectProject(id) {
  const route = currentRoute();
  if (route.screen === "city") {
    selected = id;
    render();
    reload();
    return;
  }
  const hash = { building: router.buildingHash(id), floor: route.agent ? router.floorHash(id, route.agent) : router.buildingHash(id),
    lobby: router.lobbyHash(id), control: router.controlHash(id) }[route.screen];
  window.location.hash = hash;
}

function noticeFor(route) {
  if (failure) {
    const lead = failure.name === "ApiError" && failure.status !== 0 ? failure.message : NETWORK_TEXT;
    return { kind: "error", lead, retry: true };     // city.html "First read failed": the sentence is the band's lead and "Try again" stands under it
  }
  const found = [];
  const unread = [];
  for (const p of snapshot.projects) {
    if (route.project && p.id !== route.project) continue;
    const detail = snapshot.details[p.id];
    const refused = detail && detail.error && detail.error.status === 412 ? detail.error : null;
    if (refused || !(p.config && p.config.accepted)) {
      const text = (refused && refused.message) || p.message || "its configuration is not accepted yet";
      const next = (refused && refused.next) || null;      // the command that accepts it, as the service gave it with the refusal
      // the service's sentence ends with the command; it is drawn once, in the component
      found.push({ name: p.name, text: next && text.trim().endsWith(next) ? text.trim().slice(0, -next.length).trim() : text, command: next });
    } else if (detail && detail.error) unread.push(`${p.name}: ${detail.error.message}`);
  }
  if (!found.length && unread.length) return { kind: "error", text: `A project could not be read: ${unread.join("; ")}`, retry: true };
  if (!found.length) return null;
  // The service's own text, in a wrapped monospace block: it names the exact command to type in the terminal.
  return { kind: "error", lead: `${found.map((f) => f.name).join(", ")} ${found.length === 1 ? "is" : "are"} not accepted yet: the terminal accepts a configuration.`,
    text: found[0].text, command: found[0].command, mono: true, more: found.slice(1).map((f) => ({ text: f.text, command: f.command })) };
}

function ensureView(route) {
  const key = `${route.screen}|${route.project}|${route.agent}`;
  if (view && view.key === key) return;
  if (view) view.dispose();
  if (route.screen === "city") {
    const city = createCityView(frame);
    view = { key, screen: "city", city, dispose: () => city.dispose() };
  } else if (route.screen === "building") {
    const building = createBuildingView(frame, { refresh: () => reloaded(), selectRequest });
    view = { key, screen: "building", building, dispose: () => building.dispose() };
  } else if (route.screen === "floor") {
    const floor = createFloorView(frame, { refresh: () => reloaded() });
    view = { key, screen: "floor", floor, dispose: () => floor.dispose() };
  } else if (route.screen === "control") {
    const control = createControlView(frame);
    view = { key, screen: "control", control, dispose: () => control.dispose() };
  } else if (route.screen === "lobby") {
    const lobby = createLobbyView(frame, { project: route.project, onChanged: () => reloaded() });
    view = { key, screen: "lobby", lobby, dispose: () => lobby.dispose() };
  } else {
    const placeholder = createPlaceholder(frame, route);
    view = { key, screen: route.screen, placeholder, dispose: () => placeholder.el.remove() };
  }
}

function render() {
  if (!frame) return;
  const route = currentRoute();
  const now = new Date();
  const projects = snapshot.projects;
  const scope = route.project || null;
  const state = model.screenState(snapshot, failure);
  const loading = state === "loading";
  const chosen = route.project || selected;
  const project = projects.find((p) => p.id === chosen) || null;
  const routeProject = route.project ? projects.find((p) => p.id === route.project) : null;
  const known = route.screen === "city" || routeProject || !snapshot.loaded;

  const key = `${route.screen}|${route.project}|${route.agent}`;
  const changed = drawnKey !== null && drawnKey !== key;
  frame.setScreen(route, {
    projectName: routeProject ? routeProject.name : (project ? project.name : null), projectId: project ? project.id : null,
    leaf: route.agent ? route.agent.charAt(0).toUpperCase() + route.agent.slice(1) : null,
  });
  drawnKey = key;
  frame.el.classList.toggle("is-stale", Boolean(failure) && snapshot.loaded);
  // A-16: a project whose configuration is not accepted keeps the last data read on every screen of it, dimmed (one class); the band says why.
  // A project's screens dim for that project; the City for any project that is not accepted.
  const dimmed = route.project ? routeProject : project;
  // On the City (round 4) the two cards and the tracking bar dim while any project is not accepted: their sums span every project (city.html).
  const dims = route.screen === "city" ? model.cityDims(projects, snapshot.details) : Boolean(dimmed) && model.acceptance(dimmed, snapshot.details[dimmed.id]).kept;
  frame.el.classList.toggle("is-unaccepted", state === "ready" && dims);

  frame.switcher.update({
    projects: projects.map((p) => ({
      id: p.id, name: p.name, accepted: Boolean(p.config && p.config.accepted),
      badge: snapshot.details[p.id] && snapshot.details[p.id].status ? (snapshot.details[p.id].status.pending || []).length : (p.open_pending || 0),
      sub: model.projectSub(snapshot, p.id),
    })),
    selectedId: chosen,
    heading: route.screen === "city" ? "Projects · choose the one the tracking bar follows" : "Projects · open the same screen in",
  });
  frame.kpis.update(state === "ready" ? model.kpiSums(snapshot, scope) : null, state);
  const rows = model.waitingRows(snapshot, now, scope);
  frame.setProjects(projectsOf(snapshot));
  const track = state === "ready" ? model.tracking(snapshot, chosen, now) : null;
  frame.track.set(track, state === "loading" ? "loading" : state === "error" ? "empty" : (track ? "ready" : "empty"), Boolean(failure) && snapshot.loaded);
  frame.notice(noticeFor(route));

  ensureView(route);
  frame.dockWaiting();
  // the inbox button of a phone's bottom bar and, off the City, the card at the bottom right (the City's view draws its own rows into the same card)
  const waiting = state === "ready" ? "ready" : state;
  frame.waitingMenu.set(rows, waiting);
  if (view.screen !== "city") frame.waitingCard.set(rows, waiting);
  if (view.screen === "city") {
    const city = model.city(snapshot, now);
    view.city.update({ city, selectedId: chosen, state, snapshot, now });
  } else if (view.screen === "control") {
    const detail = routeProject ? snapshot.details[routeProject.id] : null;
    const found = model.acceptance(routeProject, detail);
    view.control.update({ reload: reloads, loaded: snapshot.loaded, unread: Boolean(failure) && !snapshot.loaded, known: Boolean(routeProject), accepted: found.accepted, kept: found.kept, projectId: route.project, projectName: routeProject ? routeProject.name : "", tab: route.tab });
  } else if (view.screen === "lobby") {
    view.lobby.update({ reload: reloads, snapshot, route, now, projectName: routeProject ? routeProject.name : "" });
    if (!known) frame.notice({ kind: "error", text: "The service has no such project." });
  } else {
    if (view.screen === "building") view.building.update({ snapshot, route, now, reload: reloads });
    else if (view.screen === "floor") view.floor.update({ snapshot, route, now, reload: reloads });
    else view.placeholder.update(snapshot, route.project, route.agent ? `Floor of ${route.agent}` : "");
    if (!known) frame.notice({ kind: "error", text: "The service has no such project." });
  }

  if (snapshot.loaded) {
    const all = model.waitingRows(snapshot, now, null);
    if (knownDecisions) {
      for (const row of all) if (!knownDecisions.has(`${row.project}:${row.id}`)) frame.announce(`New decision: ${row.kind}, ${row.title}`);
    }
    knownDecisions = new Set(all.map((row) => `${row.project}:${row.id}`));
  }
  if (changed) frame.focusHeading();
}

window.addEventListener("hashchange", () => {
  if (!frame) return;
  render();
  if (followed(currentRoute()) !== lastFollowed) reload();
});
document.addEventListener("visibilitychange", () => {
  if (!frame) return;
  if (document.hidden) stopPolling();     // a reload still running is left behind; the watcher keeps no timer while hidden
  if (watcher) watcher.visibilityChanged();    // visible again: one reload
});

initMode();      // the light/dark preference is applied before the first draw
start();
