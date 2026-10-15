// The Lobby (handoff lobby.md): the planning agent's floor. A room (lobby-scene.js) beside a 380 px panel (R-43) whose Conversation tab
// holds the messages, each request's line and its decisions (the plan card under the message that produced it), and at the bottom
// the composer with "New request" beside "Send"; that button puts the form in the place of the thread and the composer (R-44). The page decides nothing: it sends what the person typed (`say`, or `request`
// then `route`), reads `conversation` and `task` and draws what came. The conversation is read every 2 seconds while a job of
// this screen runs, never while the document is hidden, and again, with the request bodies, the documents and the planning agent's
// task bodies, whenever the page reloads because the store changed (the stamp `reload` of what `update` is given). The Inbox, Desk and Agent tabs are the
// Floor's modules (floor/inbox.js, desk-tab.js, viewer.js, agent-tab.js) given the planning agent: lobby-inbox.js, lobby-desk.js
// and lobby-agent.js hand them their data, and every write they send goes through floor/actions.js.

import * as api from "../api.js";
import { failureText } from "../cards/plan-rows.js";
import { h } from "../dom.js";
import * as fm from "../floor-model.js";
import { createOwlList } from "../floor/owl-list.js";
import { focusOpenLink } from "../floor/widgets.js";
import * as origin from "../frame/origin.js";
import { actions } from "../floor/actions.js";
import { createTasksTab } from "../floor/tasks-tab.js";
import { openOwl } from "../owl-words.js";
import { createPanel } from "../frame/panel.js";
import { can as pageMay, fingerprint } from "../permissions.js";
import * as router from "../router.js";
import { afterNumber, createRequest, routeRequest, sendTurn, waitFor, worthSending } from "./lobby-actions.js";
import { createLobbyAgent } from "./lobby-agent.js";
import { createComposer } from "./lobby-composer.js";
import { createLobbyDesk, createLobbyViewer } from "./lobby-desk.js";
import { createForm } from "./lobby-form.js";
import { createLobbyInbox } from "./lobby-inbox.js";
import {
  NOT_ACCEPTED_TEXT, QUEUED_NOTICE, cancelCount, canvasLabel, hasQueued, inboxParts, isNamed, lobbyDecisions, mergeMessages, noticeFor, notRoutedNotice, placeBlocks,
  RESOLVED_LINES, TABS, inboxBodies, pollInterval, readAfter, roomModel, runNote, signatureOf, tabOf, wantedBodies,
} from "./lobby-model.js";
import { createCancelDialog } from "./lobby-request.js";
import { mountLobbyScene } from "./lobby-scene.js";
import { createTabs } from "./lobby-tabs.js";
import { bindSwipe } from "../swipe.js";
import { createThread } from "./lobby-thread.js";
import * as model from "../model.js";
import { worldModel } from "../world-model.js";

const RETRY_READ_MS = 60000;      // a read of the commands or the flows that failed is tried again after a minute

/**
 * Create the Lobby of `project` in `frame`. options: {project, onChanged(): Promise (the page reads the project again)}.
 * Returns {update({snapshot, route, now, projectName, reload}), dispose()}.
 */
export function createLobbyView(frame, { project, onChanged }) {
  const abort = new AbortController();
  const signal = abort.signal;
  let disposed = false;
  let messages = [];
  let loaded = false;
  let turn = null;                    // the job of a `say` that is running, or null
  const routing = new Set();          // request ids whose `route` job is running
  const chosenFlow = new Map();       // request id -> the flow chosen in the form (for "Route it" after a busy answer)
  const bodies = new Map();           // request id -> {sig, body}
  const reading = new Map();          // request id -> the read of its `task` body that is running
  let last = { snapshot: null, route: null, now: new Date(), projectName: "" };
  let notice = null;                  // the composer's: a turn that was not sent or failed
  const routeNotices = new Map();     // request id -> {title, text}: a route that failed, shown under that request's line
  let timer = null;
  let readingConversation = false;
  let flowsAsked = false;
  let modelsAsked = false;            // the models of the gate file, read once with the `skills` operation: the form's "Model" select
  let commandsAsked = false;
  let commandsKey = null;             // what the page could do when the "/" list was last asked for: the service filters the list by the policy, so it is read again when this changes (accept-config), not on every reload
  let commandsSeq = 0;                // the newest ask: an older answer that arrives late is dropped
  let commandsFailedAt = 0;           // a read that failed is tried again after RETRY_READ_MS, not on every update
  let flowsFailedAt = 0;
  let formOpen = false;               // the "New request" form stands in the place of the thread and the composer (R-44); its draft stays in its fields
  let flows = null;                   // the project's flows, read once: the form's select and the one beside "Route it" after a reload (E-20)
  let requestFollowed = null;         // the request whose route was followed (scrolled to, title focused); forgotten when the route names none
  let accepted = true;
  let frozen = false;                 // not accepted, but the thread was read before: it stays on the screen, dimmed, and does nothing (A-16)
  let again = false;                  // a read of the conversation was asked for while one was running
  let conversationRead = Promise.resolve();    // the read that is running, and the one more that was asked for
  let viewerWas = false;
  let shownPath = null;               // the document the viewer showed last: the focus goes back to what opened it when the viewer closes
  let leftInbox = true;               // the Inbox was left since it was last drawn: a resolved card goes
  let reloaded = null;                // the page's reload stamp last seen: when it moves the store changed, and everything shown is read again
  let changes = 0;                    // how many times it moved: a read that began before the last move is not fresh when it ends

  // What the page may do in this project (js/permissions.js): read from the project's entry in the snapshot at every draw. The thread, the composer, the
  // form, the Inbox, the Tasks tab and the Agent tab ask this getter; the service still refuses what it must (409).
  const may = (op, kind) => pageMay(last.snapshot ? (last.snapshot.projects || []).find((p) => p.id === project) : null, op, kind);

  // --- the pieces ---------------------------------------------------------------------------------------------------------
  const panel = createPanel({ screen: "lobby", title: "Planning agent", subtitle: "Lobby · floor 0", icon: "message-square", tone: "theme", width: "lobby" });
  panel.el.classList.add("wb-panel-lobby");
  const tabs = createTabs();
  const refresh = async () => {
    invalidate();
    await onChanged();
    await readConversation();
    await settled();      // the cards are drawn from the bodies read again before the caller goes on
  };
  const thread = createThread({
    api, project, signal, onChanged: refresh, can: may,
    onCancel: (request) => openCancel(request),
    onRoute: (request, flow) => routeAgain(request, flow), announce: (text) => frame.announce(text),
  });
  const waiting = h("p", { class: "wb-empty wb-lobby-waiting", hidden: true, text: NOT_ACCEPTED_TEXT });
  const form = createForm({ onCreate: (values) => create(values), onBack: () => closeForm() });
  const conversationPanel = h("div", { class: "wb-lobby-tabpanel", role: "tabpanel", id: tabs.panelId("conversation"), "aria-labelledby": tabs.tabId("conversation") }, waiting, thread.el, form.el);
  // the Inbox, Desk and Agent tabs: the Floor's modules with the planning agent (lobby-inbox.js, lobby-desk.js, lobby-agent.js)
  const waitingLine = () => h("p", { class: "wb-empty-line wb-lobby-waiting", hidden: true, text: NOT_ACCEPTED_TEXT });
  const inbox = createLobbyInbox({ project, now: () => new Date(), refresh: () => { refresh(); }, can: may });
  const desk = createLobbyDesk({
    project, open: (path) => { window.location.hash = router.lobbyDeskHash(project, path); }, changed: () => { drawTabs(); drawRoom(); },
  });
  const agent = createLobbyAgent({ project, now: () => new Date(), refresh: () => { refresh(); }, changed: () => drawTabs(), can: may });
  const tasks = createTasksTab({
    project, now: () => new Date(), refresh: () => { refresh(); }, api: actions, can: may,
    links: { request: () => router.lobbyHash(project), inbox: (id) => router.lobbyHash(project, "inbox", id), open: (path) => router.lobbyDeskHash(project, path) },
  });
  const sections = { inbox: { waiting: waitingLine(), body: inbox.el }, desk: { waiting: waitingLine(), body: desk.el }, tasks: { waiting: waitingLine(), body: tasks.el }, agent: { waiting: waitingLine(), body: agent.el } };
  const tabPanels = {};
  for (const [id, part] of Object.entries(sections)) {
    tabPanels[id] = h("div", { class: "wb-lobby-tabpanel wb-lobby-scroll", role: "tabpanel", id: tabs.panelId(id), "aria-labelledby": tabs.tabId(id), hidden: true }, part.waiting, part.body);
  }
  const composer = createComposer({ onSend: (text) => send(text), onNew: () => openForm() });
  const footer = h("div", { class: "wb-lobby-footer" }, composer.el);
  const cancelDialog = createCancelDialog({ api, project, onChanged: refresh });
  panel.body.classList.add("wb-lobby-body");
  panel.body.append(conversationPanel, tabPanels.inbox, tabPanels.desk, tabPanels.tasks, tabPanels.agent);
  panel.el.insertBefore(tabs.bar, panel.body);
  let shownTab = "conversation";      // the tab on show: a swipe on the panel on a phone goes to the one beside it (A-77)
  const swipe = bindSwipe(panel.body, {
    ids: () => TABS.map(([id]) => id), current: () => shownTab, enabled: () => !tabs.bar.hidden,
    go: (id) => { window.location.hash = router.lobbyHash(project, id); },
  });
  panel.el.append(footer);
  // the owls of the room, each selected on its own (PAR-7e): what the world last gave for them, and their twin list for the keyboard
  let owls = [];
  const owlList = createOwlList({
    hashOf: (target) => router.lobbyHash(project, target.route.tab, target.route.id),
    highlight: (id, source) => scene.highlight(id, source),
  });
  frame.main.append(panel.el, owlList.el, cancelDialog.el);
  // "Close" and a phone's dialog go to the one hash the frame's key handler also uses: the tab the document was opened from (frame/origin.js)
  const viewer = createLobbyViewer({ frame, panel: panel.el, project, listed: (path) => desk.listed(path), onClose: () => { origin.close(last.route || router.parse(window.location.hash)); } });
  const panelHead = panel.el.querySelector(".wb-panel-head");
  const scene = mountLobbyScene(frame, panel.el, { onDoor: () => { window.location.hash = router.controlHash(project); }, onSelect: (id) => openFromScene(id) });

  // --- reading ------------------------------------------------------------------------------------------------------------
  /** A body that was drawn stays drawn (a card keeps its note and its focus) but is read again: its signature no longer matches. */
  function invalidate() {
    for (const entry of bodies.values()) entry.sig = null;
  }

  function redraw() {
    if (disposed) return;
    const status = last.snapshot && last.snapshot.details[project] && last.snapshot.details[project].status;
    const requests = status ? status.requests || [] : [];
    const pending = status ? status.pending || [] : [];
    const held = {};
    for (const [id, entry] of bodies) held[id] = entry.body;
    for (const id of [...routeNotices.keys()]) {      // a request that is routed or cancelled has no failed route to show (one not read yet keeps its notice)
      const row = requests.find((r) => r.id === id);
      if (row && row.state !== "requested") routeNotices.delete(id);
    }
    thread.update({ messages, requests, pending, bodies: held, now: last.now, loading: !loaded, routing, notices: routeNotices, flows, remembered: chosenFlow });
    form.setRequests(requests);      // R-46: "After request" offers the requests that are not final
    if (wantsRequest()) setTimeout(followRequest, 0);      // after the frame's own focus of a new screen's heading
  }

  /** The route names a request line (`.../conversation/request/<n>`) that was not followed yet. */
  function wantsRequest() {
    const route = last.route;
    return Boolean(route) && route.request !== null && route.request !== undefined && tabOf(route) === "conversation" && requestFollowed !== route.request;
  }

  /** Scroll to the request's block and focus its title, once per visit of the route; a block not drawn yet is asked for again at the next draw. */
  function followRequest() {
    if (disposed || !wantsRequest() || thread.el.hidden || conversationPanel.hidden) return;
    if (thread.focusRequest(last.route.request)) requestFollowed = last.route.request;
  }

  /**
   * Read the conversation after the newest message. A call made while a read runs asks for one more and returns the promise of the
   * read that is running, which ends when that one more has been done too: the caller (the end of a route) then knows the messages.
   */
  function readConversation() {
    if (disposed) return Promise.resolve();
    if (readingConversation) {
      again = true;
      return conversationRead;
    }
    conversationRead = readOnce();
    return conversationRead;
  }

  async function readOnce() {
    readingConversation = true;
    try {
      const got = await api.conversation(project, { after: readAfter(messages), signal });       // a queued line is read again until its reply exists
      const next = mergeMessages(messages, got.messages);
      const changed = next.length !== messages.length;
      messages = next;
      if (changed || !loaded) {
        loaded = true;
        redraw();
        drawTabs();
        drawRoom();
      }
    } catch (e) {
      if (e && e.name === "AbortError") return;
      // a project not accepted yet, or a service that did not answer: the frame says so; the next read tries again
    } finally {
      readingConversation = false;
    }
    if (again) {
      again = false;
      await readConversation();
    }
  }

  function schedule() {
    clearTimeout(timer);
    timer = null;
    if (disposed) return;
    const ms = pollInterval({ jobRunning: turn !== null || routing.size > 0 || hasQueued(messages), hidden: document.hidden });
    if (ms !== null) timer = setTimeout(tick, ms);
  }

  async function tick() {
    await readConversation();
    schedule();
  }

  function readBody(id, sig) {
    if (reading.has(id)) return;
    const began = changes;
    const run = (async () => {
      try {
        const body = await api.task(project, id, { signal });
        bodies.set(id, { sig: began === changes ? sig : null, body });     // null: the store changed meanwhile, read again below
        redraw();
        if (tabOf(last.route) === "inbox") drawTabs();      // P-6: the Inbox's resolved lines come from these bodies
      } catch (e) {
        if (e && e.name === "AbortError") return;
        // a failed read is remembered like a read one (its signature): not tried again on every update, but when the request changes or the store does (a 404: the body is gone)
        const held = bodies.get(id);
        bodies.set(id, { sig: began === changes ? sig : null, body: e && e.status === 404 ? null : held ? held.body : null });
        redraw();
      } finally {
        reading.delete(id);
        if (began !== changes && !disposed) {
          const status = last.snapshot && last.snapshot.details[project] && last.snapshot.details[project].status;
          if (status) readBodies(status.requests || [], status.pending || []);
        }
      }
    })();
    reading.set(id, run);
  }

  /** Wait for the reads of request bodies that are running. */
  async function settled() {
    while (reading.size) await Promise.all([...reading.values()]);
  }

  function readBodies(requests, pending) {
    const placed = placeBlocks(messages, requests);
    // P-6: with the Inbox open every request is read (a decision of a request the conversation does not show, a cancelled request's lines), up to MAX_INBOX_BODIES
    const wanted = wantedBodies(placed, requests, pending);
    const ids = tabOf(last.route) === "inbox" ? [...new Set([...wanted, ...inboxBodies(requests, pending)])] : wanted;
    for (const id of ids) {
      const request = requests.find((r) => r.id === id);
      const sig = signatureOf(request, pending);
      const held = bodies.get(id);
      if (!held || held.sig !== sig) readBody(id, sig);
    }
  }

  /** A task of the planning agent is queued for a slot and is not held (M-24): its owl is ready. */
  function queuedPlanner(status) {
    const detail = last.snapshot && last.snapshot.details[project];
    const planner = detail && Array.isArray(detail.agents) ? detail.agents.find((a) => a.name === "planning") : null;
    return Boolean(planner) && planner.enabled !== false && planner.acting_mode !== "stopped" && fm.queuedFree(planner, status) > 0;   // a stopped or disabled planner is off, whatever is queued
  }

  function drawRoom() {
    const status = last.snapshot && last.snapshot.details[project] && last.snapshot.details[project].status;
    const requestRow = status ? model.pickRequest(status, model.requestChoice(project)) : null;
    const room = roomModel({
      working: turn !== null || routing.size > 0 || Boolean(model.routingRequest(status)), decisions: status ? lobbyDecisions(status).length : 0, hasMessages: messages.length > 0,
      accepted, request: requestRow, ready: Boolean(status), documents: desk.rows(), queued: accepted && queuedPlanner(status),
    });
    const words = {
      tips: room.tips, board: room.board, door: true, doorTip: room.tips.door, state: room.state, window: room.window, decisions: room.decisions,
      sheets: room.sheets, drawers: room.drawers, documents: room.documents,
    };
    const world = worldModel(last.snapshot, last.now, { selectedId: project, focus: project, floor: "planning", room: words, ready: Boolean(status) });
    owls = world.room && Array.isArray(world.room.owls) ? world.room.owls : [];
    owlList.update(owls);
    scene.update(world, canvasLabel(last.projectName, room));
  }

  /** What runs: the router's run on a request, else the running tasks (the model words it: `runNote`). The composer is busy only while its own turn is sent; this note never blocks it. */
  function runningNote() {
    const status = last.snapshot && last.snapshot.details[project] && last.snapshot.details[project].status;
    return accepted ? runNote(status, last.now, project) : null;
  }

  function drawComposer() {
    composer.set({ sending: turn !== null, notice, disabled: !accepted, running: runningNote(), say: may("say"), request: may("request") });
  }

  /** A click in the room: the board opens the Tasks tab, the tray the Inbox, the bookcase the Desk tab, a sheet its document, the owl the Agent tab. */
  function openFromScene(id) {
    if (disposed) return;
    if (id === "tasks") window.location.hash = router.lobbyHash(project, "tasks");
    else if (id === "tray") window.location.hash = router.lobbyHash(project, "inbox");
    else if (id === "desk") window.location.hash = router.lobbyHash(project, "desk");
    else if (id === "agent") window.location.hash = router.lobbyHash(project, "agent");
    else if (openOwl(owls, id, (tab, n) => { window.location.hash = router.lobbyHash(project, tab, n); })) return;      // an owl of a task, or of a free place: its task, its decision or the Agent tab
    else if (String(id).startsWith("sheet:")) window.location.hash = router.lobbyDeskHash(project, String(id).slice(6));
  }

  /** The Inbox, Desk and Agent tabs from what the page last read. Each module redraws only what changed. */
  function drawTabs() {
    if (disposed || !last.snapshot) return;
    const { snapshot, route, now } = last;
    const tab = tabOf(route);
    const detail = snapshot.details[project];
    const status = detail && detail.status;
    const model = agent.update({ snapshot, tab });
    desk.update({ tab, ready: Boolean(snapshot.loaded && accepted) });
    if (tab === "tasks" && (accepted || frozen)) {
      tasks.update({ tasks: model ? model.tasks : [], requests: status ? status.requests || [] : [], pending: status ? status.pending || [] : [], loading: !snapshot.loaded || !model, reload: reloaded, unaccepted: frozen, selected: route.pending });
    }
    if (tab !== "tasks") tasks.forget();      // an owl's click names a task (PAR-7e): the next click on the same owl opens it again
    if (tab !== "inbox" && !leftInbox && !inbox.busy()) {      // a card whose job still runs keeps its state until it ends
      inbox.reset();
      leftInbox = true;
    }
    if (tab !== "inbox") return;
    leftInbox = false;
    if (!accepted && !frozen) return;
    // Which plans have their card under a message is known only once the conversation was read: until then no plan is drawn as a card
    // (it would be drawn here, then be replaced by a line, and lose a note typed in it).
    const whole = status ? inboxParts(status, messages) : { cards: [], pointers: [] };
    const cards = loaded ? whole.cards : whole.cards.filter((item) => item.kind !== "plan");
    const withheld = whole.cards.length - cards.length;
    const parts = { cards, pointers: whole.pointers };
    const held = {};
    for (const [id, entry] of bodies) if (entry.body) held[id] = entry.body;
    const ids = [...(status ? status.requests || [] : []).map((r) => r.id), ...(model ? model.tasks.map((t) => t.id) : [])];
    inbox.update({
      cards: parts.cards, pointers: parts.pointers, requests: status ? status.requests || [] : [],
      resolved: fm.resolvedLines({ ...held, ...agent.bodies() }, ids, now, RESOLVED_LINES), selected: route.pending, loading: !snapshot.loaded || (withheld > 0 && cards.length === 0),
    });
  }

  // --- the "New request" form, in the place of the thread and the composer (R-44) ---------------------------------------------------
  let conversationShown = true;      // the Conversation tab is the one open, with nothing over it (a document) and the project readable

  /** Draw what the Conversation holds: the thread and the composer, or the form. `visible` says whether the Conversation is on show at all. */
  function applyForm(visible = conversationShown) {
    conversationShown = visible;
    const readable = accepted || frozen;
    const showForm = visible && formOpen && readable;
    form.open(showForm);
    thread.el.hidden = showForm || !readable;
    footer.hidden = !visible || showForm;
  }

  function openForm() {
    if (disposed || !accepted || !may("request")) return;
    formOpen = true;
    applyForm();
    form.focus();
  }

  function closeForm() {
    formOpen = false;
    applyForm();
    composer.focus();
  }

  // --- what the person does -------------------------------------------------------------------------------------------------
  async function send(text) {
    if (!worthSending(text) || turn !== null || !accepted || !may("say")) return;
    notice = null;
    composer.set({ sending: true, notice: null, disabled: false });
    let started;
    try {
      started = await sendTurn(api, project, text, { signal });
    } catch (e) {
      if (e && e.name === "AbortError") return;
      notice = noticeFor(e, "post");        // the text stays in the field
      drawComposer();
      composer.focus();
      return;
    }
    composer.clear();
    turn = started.job;
    drawComposer();
    drawRoom();
    schedule();
    readConversation();                     // at once: the operation stores the person's line before the router runs
    let done = null;
    try {
      done = await waitFor(api, started, { signal });
    } catch (e) {
      if (e && e.name === "AbortError") return;
      notice = { title: "The turn failed", text: failureText(e) };
    }
    turn = null;
    if (done && done.state === "failed") {
      const failure = done.error || {};
      notice = noticeFor({ status: failure.status, word: failure.error, message: failure.message }, "job");
    }
    drawComposer();
    drawRoom();
    schedule();
    await refresh();
    if (!disposed) composer.focus();
  }

  async function followRoute(id, started) {
    routing.add(id);
    schedule();
    redraw();
    drawRoom();
    let done = null;
    let problem = null;
    try {
      done = await waitFor(api, started, { signal });
    } catch (e) {
      if (e && e.name === "AbortError") return null;
      problem = failureText(e);
    }
    routing.delete(id);
    if (done && done.state === "failed") problem = (done.error && done.error.message) || "The job failed.";
    const result = done && done.result ? done.result : null;
    if (!problem && result && result.queued === true) {        // A-23: the router answers another request; the service routes this one when it ends
      routeNotices.set(id, QUEUED_NOTICE);
      redraw();
      drawRoom();
      schedule();
      await refresh();
      return result;
    }
    if (!problem && result && result.routed === false) {
      problem = (result.failure && result.failure.reason) ? `The router could not run: ${result.failure.reason}.` : "The request could not be planned.";
    }
    if (problem) routeNotices.set(id, notRoutedNotice(id, problem));
    else routeNotices.delete(id);
    redraw();
    drawRoom();
    schedule();
    await refresh();
    await settled();
    if (!problem && result && result.pending_id) frame.announce(`A decision waits for you: request ${id}`);
    if (!disposed && result && result.pending_id) {
      // a request a message names has its plan under that message; one made from the form has its card in the Inbox (OPEN-24)
      if (isNamed(messages, id)) thread.focusDecision(id, result.pending_id);
      else window.location.hash = router.lobbyHash(project, "inbox", result.pending_id);
    }
    return result;
  }

  async function create(values) {
    if (!may("request")) return;
    if (!worthSending(values.text)) {
      form.markEmpty();
      return;
    }
    if (afterNumber(values.after).invalid) {
      form.set({ creating: false, error: "After request: type the number of a request, such as 3.", disabled: false });
      return;
    }
    notice = null;
    drawComposer();
    form.set({ creating: true, error: "", disabled: false });
    let result;
    try {
      result = await createRequest(api, project, values, { signal, route: may("route") });      // without `route` the request is made and waits for its route
    } catch (e) {
      if (e && e.name === "AbortError") return;
      form.set({ creating: false, error: failureText(e), disabled: false });     // the typed text stays
      return;
    }
    if (values.flow) chosenFlow.set(result.request, values.flow);
    if (result.unrouted) {
      redraw();
    } else if (result.error) {
      routeNotices.set(result.request, notRoutedNotice(result.request, failureText(result.error)));
      redraw();
    } else {
      await followRoute(result.request, result.started);
    }
    form.reset();
    form.set({ creating: false, error: "", disabled: false });
    formOpen = false;
    applyForm();
    if (result.error || result.unrouted) await refresh();
  }

  async function routeAgain(request, flow) {
    if (routing.has(request.id) || !may("route")) return;
    routeNotices.delete(request.id);
    const outcome = await routeRequest(api, project, request.id, flow || chosenFlow.get(request.id), { signal });
    if (outcome.error) {
      routeNotices.set(request.id, notRoutedNotice(request.id, failureText(outcome.error)));
      redraw();
      return;
    }
    await followRoute(request.id, outcome.started);
  }

  function openCancel(request) {
    cancelDialog.open(request, cancelCount(request));
  }

  // --- the page's poll ------------------------------------------------------------------------------------------------------
  function onVisibility() {
    if (document.hidden) {
      clearTimeout(timer);
      timer = null;
    } else {
      schedule();       // the busy poll of a job that still runs; the page reloads on return, which reads the rest
    }
  }
  document.addEventListener("visibilitychange", onVisibility);

  return {
    /** Called by the page after every read of the projects: snapshot (js/data.js), route (router.parse), now, the project's name. */
    update({ snapshot, route, now, projectName, reload }) {
      if (disposed) return;
      last = { snapshot, route, now, projectName: projectName || "" };
      origin.track(route);
      if (route.request === null || route.request === undefined) requestFollowed = null;
      if (reloaded !== null && reload !== reloaded) {     // the store changed: everything shown is stale, whatever its age
        changes += 1;
        invalidate();
        desk.reload();
        agent.reload();
        viewer.reload();
        readConversation();
      }
      reloaded = reload;
      const listed = (snapshot.projects || []).find((p) => p.id === project);
      const detail = snapshot.details[project];
      // Before the first read nothing is known: the screen is not declared unaccepted until the projects came.
      const found = model.acceptance(listed, detail);
      accepted = !snapshot.loaded || found.accepted;
      frozen = snapshot.loaded && !found.accepted && found.kept && loaded;
      const shown = accepted || frozen;
      for (const part of [inbox, tasks]) {      // A-16: the cards and the tasks' buttons would only be refused
        if (frozen) part.el.setAttribute("inert", "");
        else part.el.removeAttribute("inert");
      }
      const status = detail && detail.status;
      const tab = tabOf(route);
      shownTab = tab;
      tabs.set({ project, selected: tab, counts: { inbox: status ? lobbyDecisions(status).length : 0 } });
      const onConversation = tab === "conversation";
      conversationPanel.hidden = !onConversation;
      conversationPanel.setAttribute("aria-labelledby", tabs.tabId("conversation"));
      for (const [id, part] of Object.entries(sections)) {
        tabPanels[id].hidden = tab !== id;
        part.waiting.hidden = shown;
        part.body.hidden = !shown;
      }
      // a document opened on the Desk takes the panel's place (a phone: a dialog)
      const showing = tab === "desk" && accepted && route.path ? viewer.show(route.path) : viewer.show(null);
      const inline = showing === "inline";
      panel.el.classList.toggle("is-viewing", inline);
      panelHead.hidden = inline;
      tabs.setHidden(inline);
      panel.body.hidden = inline;
      applyForm(onConversation && !inline);
      if (viewerWas && !showing && shownPath !== null) {     // the viewer was closed: the focus goes back to what opened it
        const back = shownPath;
        if (tab === "inbox") inbox.focusOpen(back);
        else if (tab === "desk") setTimeout(() => desk.focusRow(back), 0);
        else focusOpenLink(panel.body, back);
      }
      viewerWas = Boolean(showing);
      shownPath = showing ? route.path : null;
      waiting.hidden = shown;
      form.set({ disabled: !accepted });
      form.setRoute(may("route"));      // without `route` the Flow select is left out and a line says so
      if (formOpen && !may("request")) {      // the policy changed while the form was open: back to the conversation
        formOpen = false;
        applyForm(onConversation && !inline);
      }
      drawComposer();
      const allowedKey = fingerprint(may);
      if (commandsKey !== null && allowedKey !== commandsKey) {
        commandsAsked = false;
        commandsFailedAt = 0;
      }
      if (accepted && !commandsAsked && Date.now() - commandsFailedAt >= RETRY_READ_MS) {
        commandsAsked = true;      // R-45: the commands of the `chat` channel as data, read once (and again when what the page may do changes); until they are known no list opens
        commandsKey = allowedKey;
        const seq = ++commandsSeq;
        api.commands(project, { signal }).then((got) => { if (seq === commandsSeq) composer.setCommands(got.commands); }).catch(() => { if (seq === commandsSeq) { commandsAsked = false; commandsFailedAt = Date.now(); } });
      }
      if (accepted && !flowsAsked && Date.now() - flowsFailedAt >= RETRY_READ_MS) {
        flowsAsked = true;
        api.flows(project, { signal }).then((got) => { flows = Array.isArray(got.flows) ? got.flows : []; form.setFlows(got.flows); redraw(); }).catch(() => { flowsAsked = false; flowsFailedAt = Date.now(); });
      }
      if (accepted && !modelsAsked && Date.now() - flowsFailedAt >= RETRY_READ_MS) {
        modelsAsked = true;
        api.skills(project, { signal }).then((got) => { form.setModels(got.models, got.default_model); }).catch(() => { modelsAsked = false; flowsFailedAt = Date.now(); });
      }
      if (status) readBodies(status.requests || [], status.pending || []);
      redraw();
      drawTabs();
      drawRoom();
      if (!loaded && accepted) tick();
      else if (timer === null) schedule();
    },
    dispose() {
      disposed = true;
      origin.reset();
      abort.abort();
      clearTimeout(timer);
      swipe.destroy();
      document.removeEventListener("visibilitychange", onVisibility);
      viewer.dispose();
      desk.dispose();
      agent.dispose();
      scene.dispose();
      owlList.el.remove();
      panel.drawer.destroy();   // before the panel leaves the page: the frame hears that nothing covers the scene
      panel.el.remove();
      cancelDialog.el.remove();
    },
    stats() {
      return scene.stats();
    },
    /** What a click on an object of the room opens (also what a test presses): the tray, the cabinet, a sheet, the desk, the board, the figure. */
    open(id) {
      openFromScene(id);
    },
  };
}
