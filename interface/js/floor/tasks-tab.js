// The Tasks tab of a floor (adjustment A-8; handoff floor.md and lobby.md, "Tasks tab"): every task of the project whose agent is
// this floor's, in groups by state (running, waiting for you, ready, planned or blocked, done, failed, cancelled), each group with
// its count. A row shows the number, the title, the skill, the state, the request, the age and the actions its state allows: Retry
// on a failed or blocked task (a blocked one with the sentence the runtime stored beside it, A-31), "Open in the Inbox" when a decision waits,
// "Go ahead" and "Drop the after" on a planned task that waits for another (A-29, and its reasons on the row). A done task shows the paths it returned (each with
// "Open" under docs/); a failed one its failure word and the ending of its last run. A row expands into the task's runs, the block
// the Agent tab draws for its current task. The rows come from `status`; `task` is read for the first twelve rows while the tab is
// open (the failed ones first, then the done ones, then the rest, since their failure and their paths are only in the body) and for a row
// when it is expanded. A body is kept until the page's reload stamp moves (the store changed) or the task's state changes. Every value is text. The writes are Retry and the two
// go-aheads, sent by task-actions.js through the client the view hands in (floor/actions.js), never through a client of this file.

import * as client from "../api.js";
import { fill, h, keepScroll, sync } from "../dom.js";
import { arrowNav } from "../frame/arrows.js";
import { icon } from "../frame/icons.js";
import { runsSection } from "./run-block.js";
import { createTaskActions } from "./task-actions.js";
import { groupTasks, rowOf } from "./tasks-model.js";
import { createCaptionsView } from "./captions-view.js";
import { createVideoCard } from "./video-card.js";
import { busyLine, chip } from "./widgets.js";

const MAX_READS = 12;       // the first rows read without being expanded (the Inbox reads twelve too)
const MEDIA_KEY = /^media:([0-9a-f]{16})$/;     // the code task of a recording carries the key media:<recording id> (runtime/media.py); its row shows the rendered video
export const NONE_TEXT = "This agent has no task yet.";

/** Run `render`, then put the keyboard focus back on the control with the same `data-key` when it was inside `container`. */
function keepFocus(container, render) {
  const active = document.activeElement;
  const key = active && container.contains(active) && active.getAttribute ? active.getAttribute("data-key") : null;
  render();
  if (!key) return;
  const next = [...container.querySelectorAll("[data-key]")].find((n) => n.getAttribute("data-key") === key);
  if (next && next.focus) next.focus({ preventScroll: true });
}

/**
 * Create the tab. env: {project, now() (a Date), refresh() (read the page's data again), api: {retry, goAhead} (floor/actions.js),
 * can(op, kind) (optional: whether the page may do an operation, js/permissions.js; Retry and the go-aheads are drawn only when it allows `retry` and `go-ahead`; all allowed when left out),
 * links: {request(requestId), inbox(pendingId or null), open(path)} (hashes built with the router)}.
 * Returns {el, update({tasks, requests, pending, loading, selected}), forget()}: tasks are floor-model.agentTasks(...) rows, requests and pending
 * the status's, loading true before the first read, `selected` the task the route names (it is opened once, with the focus on its row; `forget` lets the next route open it again).
 */
export function createTasksTab(env) {
  const el = h("div", { class: "wb-tasks-tab" });
  const groupsBox = h("div", { class: "wb-tasks-groups" });
  arrowNav(groupsBox, "button.wb-task-toggle");
  let last = { tasks: [], requests: [], pending: [], loading: true };
  const bodies = new Map();        // task id -> {body, state, at}
  const reading = new Set();
  const expanded = new Set();
  const earlierOpen = new Set();   // task ids whose "Earlier attempts" disclosure is open (closed by default)
  const videos = new Map();        // recording id -> what an open row of a recording's code task shows: the caption review and the rendered-video card (closed, with the blob URLs revoked, when the row closes)
  const rows = new Map();          // task id -> {sig, li, body, slot}: the row's nodes, made once and changed in place
  const groupNodes = new Map();    // group id -> {details, list, head, isOpen, summary}: the group's block, made once
  const opened = new Map();        // group id -> the person's choice, over "open when it holds a task"
  const actions = createTaskActions({ project: env.project, api: env.api, refresh: () => env.refresh(), redraw: () => draw(), done: (id) => bodies.delete(id), can: env.can });
  let shown = "";
  let reloaded = null;             // the page's reload stamp last seen; null until one is given
  let changes = 0;                 // how many times it moved: a read that began before the last move is not fresh when it ends
  let applied = null;              // the task the route named that was opened already (an owl's click, PAR-7e): the person closing it is not undone by the next poll
  let focusTask = null;            // the task whose row takes the focus once it is drawn

  // --- reading ---------------------------------------------------------------------------------------------------------------
  const fresh = (cached, task) => cached.state === task.state && cached.at !== 0;     // at 0: the store changed since it was read

  function ensure(task) {
    const cached = bodies.get(task.id);
    if (reading.has(task.id)) return;
    if (cached && fresh(cached, task)) return;
    reading.add(task.id);
    const began = changes;
    const stamped = () => (began === changes ? Date.now() : 0);     // 0: the store changed meanwhile, read again at once
    client.task(env.project, task.id).then((body) => {
      bodies.set(task.id, { body, state: task.state, at: stamped() });
    }).catch(() => {
      bodies.set(task.id, { body: cached ? cached.body : null, state: task.state, at: stamped() });
    }).finally(() => {
      reading.delete(task.id);
      if (began !== changes) read();
      draw();
    });
  }

  // The rows whose body is read without being expanded: the failed ones first (their failure word and ending), then the done ones
  // (their paths), then the rest in the groups' order, at most twelve; and every expanded row.
  const READ_ORDER = ["failed", "done"];

  function read() {
    if (last.loading) return;
    const groups = groupTasks(last.tasks);
    const first = READ_ORDER.map((id) => groups.find((g) => g.id === id)).filter(Boolean);
    const rest = groups.filter((g) => !READ_ORDER.includes(g.id));
    for (const task of [...first, ...rest].flatMap((g) => g.tasks).slice(0, MAX_READS)) ensure(task);
    for (const id of expanded) {
      const task = last.tasks.find((t) => t.id === id);
      if (task) ensure(task);
    }
  }

  // --- drawing ---------------------------------------------------------------------------------------------------------------
  function toggleRow(task) {
    if (expanded.has(task.id)) expanded.delete(task.id);
    else expanded.add(task.id);
    if (expanded.has(task.id)) ensure(task);
    else closeVideo(task);
    draw();
  }

  function recordingOf(task) {
    const found = MEDIA_KEY.exec(typeof task.key === "string" ? task.key : "");
    return found ? found[1] : null;
  }

  function closeVideo(task) {
    const recording = recordingOf(task);
    const card = recording ? videos.get(recording) : null;
    if (!card) return;
    card.close();
    videos.delete(recording);
  }

  /**
   * What the row of a code task of a recording shows: the caption review (floor/captions-view.js) above the rendered-video card (floor/video-card.js), made once when the row
   * opens and read again when the store changed. The review tells the card when the pipeline moved, so that the card reads again at once.
   */
  function videoOf(task) {
    const recording = recordingOf(task);
    if (!recording) return null;
    let entry = videos.get(recording);
    if (!entry) {
      const card = createVideoCard({ project: env.project, recording, api: env.api, can: env.can, now: env.now });
      const captions = createCaptionsView({ project: env.project, recording, api: env.api, can: env.can, changed: () => card.load({ quiet: true }) });
      entry = {
        el: h("div", { class: "wb-media-task" }, captions.el, card.el),
        load: (options) => { captions.load(options); card.load(options); },
        close: () => { captions.close(); card.close(); },
      };
      videos.set(recording, entry);
      entry.load();
    }
    return entry.el;
  }

  function pathRow(file) {
    const link = file.openable ? h("a", { class: "pui-link pui-theme", href: env.links.open(file.path), "aria-label": `Open ${file.path}`, text: "Open" }) : null;
    return h("li", { class: "wb-path-row" }, h("code", { class: "wb-path", text: file.path }), link);
  }

  function detailOf(task, row) {
    if (!row.hasBody) {
      const cached = bodies.get(task.id);
      return cached && !reading.has(task.id) ? h("p", { class: "wb-empty-line", text: "The runs could not be read." }) : busyLine("Loading the runs...");
    }
    if (!row.runs.length) return h("p", { class: "wb-empty-line", text: "No run yet." });
    // A-72: "This run" and the closed "Earlier attempts (n)" (run-block.js, shared with the Agent tab's current-task card)
    return runsSection(row.runs, { key: task.id, isOpen: earlierOpen.has(task.id), onToggle: () => {
      if (earlierOpen.has(task.id)) earlierOpen.delete(task.id);
      else earlierOpen.add(task.id);
      draw();
    } });
  }

  /**
   * R-39: a task is an accordion. Its header is one button, the number, the title, the state chip and a marker that turns when it opens; the rest of the row (the meta, the
   * failure, the wait lines, the paths, the actions and the runs) is its body, shown when it is opened. The disclosure keeps `aria-expanded` and `aria-controls`, and the
   * arrow keys of the group (frame/arrows.js).
   */
  function rowNode(task) {
    const row = rowOf(task, { requests: last.requests, pending: last.pending, body: (bodies.get(task.id) || {}).body || null, now: env.now() });
    const isOpen = expanded.has(task.id);
    // A row is made once and kept: its pieces are changed only when what it shows changed, and its video slot (the caption review and the rendered-video card)
    // is never taken out of it, so a poll or a store change leaves the person's place in a long review where it was.
    let entry = rows.get(task.id);
    if (!entry) {
      entry = { sig: "", li: h("li", { "data-task": String(task.id) }), body: h("div", { class: "wb-task-body", id: `wb-task-body-${task.id}` }), slot: h("div", { class: "wb-task-media" }) };
      rows.set(task.id, entry);
    }
    const sig = JSON.stringify([row, isOpen, earlierOpen.has(task.id), !row.hasBody && [bodies.has(task.id), reading.has(task.id)], actions.signature()]);     // a body being read again changes nothing a row shows while the old one stands
    if (sig === entry.sig) return entry.li;
    entry.sig = sig;
    const detailId = `wb-task-detail-${task.id}`;
    const toggle = h("button", { class: "pui-btn pui-link wb-task-toggle wb-task-head", type: "button", "data-key": `toggle-${task.id}`, "aria-expanded": isOpen ? "true" : "false", "aria-controls": `wb-task-body-${task.id}` },
      h("span", { class: "wb-task-num wb-task-n", text: row.number }), h("span", { class: "wb-task-title", text: row.title }), chip(row.word, row.tone),
      h("span", { class: "wb-task-mark", "aria-hidden": "true" }, icon("chevron-down", 16)));
    toggle.addEventListener("click", () => toggleRow(task));
    const meta = h("div", { class: "wb-task-meta wb-muted" },
      row.skill ? h("code", { class: "wb-task-skill", text: row.skill }) : null,
      row.request ? h("span", { class: "wb-task-request" }, h("a", { class: "pui-link pui-theme", href: env.links.request(row.request.id), text: row.request.label })) : null,
      h("span", { class: "wb-task-age", text: row.age }));
    const buttons = actions.nodes(task, { pending: last.pending, links: env.links });
    const showNote = row.note && (task.state === "failed" || task.state === "cancelled");     // a blocked task's sentence stands beside Retry
    const failure = row.failure ? `${row.failure.failure}${row.failure.ending ? ` · ${row.failure.ending}` : ""}` : "";
    entry.li.setAttribute("class", `wb-task wb-task-acc${isOpen ? " is-open" : ""}`);
    entry.body.hidden = !isOpen;
    sync(entry.slot, isOpen ? videoOf(task) : null);
    sync(entry.body,
      meta,
      failure ? h("p", { class: "wb-task-failure", text: failure }) : null,
      row.waits.map((line) => h("p", { class: "wb-task-waits wb-muted", text: line })),
      showNote ? h("p", { class: "wb-task-note wb-muted", text: row.note }) : null,
      row.returned.length ? h("ul", { class: "wb-paths wb-task-paths" }, row.returned.map(pathRow)) : null,
      buttons.length ? h("div", { class: "wb-task-actions" }, buttons) : null,
      actions.failure(task.id),
      entry.slot,
      h("div", { class: "wb-task-detail", id: detailId, hidden: !isOpen }, isOpen ? detailOf(task, row) : null));
    sync(entry.li, toggle, entry.body);
    return entry.li;
  }

  /** A group (R-39): a bordered block; its header has the state's icon in the state's colour (faint when the group is empty), the name in small capitals and the count at the right. The block is made once; its rows are kept (rowNode). */
  function groupNode(group) {
    const isOpen = group.count > 0 && (opened.has(group.id) ? opened.get(group.id) : true);
    let entry = groupNodes.get(group.id);
    if (!entry) {
      const details = h("details", { class: "wb-task-group", "data-group": group.id });
      entry = { details, list: h("ul", { class: "wb-task-list", role: "list" }), head: "", isOpen: false };
      details.addEventListener("toggle", () => {
        if (details.open === entry.isOpen) return;
        opened.set(group.id, details.open);
        draw();
      });
      groupNodes.set(group.id, entry);
    }
    const head = JSON.stringify([group.icon, group.tone, group.count, group.label]);
    if (head !== entry.head) {
      entry.head = head;
      entry.summary = h("summary", { class: "wb-task-group-head", "data-key": `group-${group.id}` },
        h("span", { class: `wb-tile wb-group-tile pui-soft ${group.tone}${group.count === 0 ? " is-none" : ""}`, "aria-hidden": "true" }, icon(group.icon, 14)),
        h("span", { class: "wb-task-group-name wb-group-name", text: group.label }), h("span", { class: "pui-badge pui-muted pui-soft pui-rounded-full", text: String(group.count) }));
    }
    entry.isOpen = isOpen;
    if (isOpen !== (entry.details.getAttribute("open") !== null)) {      // the attribute is the state (a person's click changes it too); the toggle event of this change finds it equal to `isOpen` and does nothing
      if (isOpen) entry.details.setAttribute("open", "");
      else entry.details.removeAttribute("open");
    }
    if (isOpen) sync(entry.list, group.tasks.map(rowNode));
    sync(entry.details, entry.summary, isOpen ? entry.list : null);
    return entry.details;
  }

  function drawNow() {
    if (last.loading) {
      if (shown !== "loading") {
        shown = "loading";
        fill(el, busyLine("Loading the tasks..."));
      }
      return;
    }
    const groups = groupTasks(last.tasks);
    const now = env.now();
    // the signature is everything a row draws: a poll that changed nothing draws nothing, so it never takes the focus away
    const key = JSON.stringify([groups.map((g) => [g.id, g.count, g.tasks.map((t) => [t.id, t.title, t.skill, t.state, t.note, t.requestId, t.waiting_for])]), last.requests.map((r) => [r.id, r.title]),
      last.pending.map((p) => [p.id, p.task_id]), [...bodies].map(([id, v]) => [id, Boolean(v.body), v.body ? [v.body.runs, v.body.pending, v.body.task] : null]), [...expanded].sort(), [...earlierOpen].sort(), [...opened], actions.signature(),
      [...reading], last.tasks.map((t) => (bodies.get(t.id) && bodies.get(t.id).body ? rowOf(t, { requests: last.requests, pending: last.pending, body: bodies.get(t.id).body, now }).age : ""))]);
    if (key === shown) return;
    shown = key;
    if (!last.tasks.length) {
      rows.clear();
      groupNodes.clear();
      fill(el, h("p", { class: "wb-empty-line", text: NONE_TEXT }));
      return;
    }
    // the nodes of a row that did not change stay where they are; the scroll position of the panel is put back whatever was replaced
    keepScroll(el, () => keepFocus(groupsBox, () => {
      sync(groupsBox, groups.map(groupNode));
      for (const id of [...rows.keys()]) if (!last.tasks.some((t) => t.id === id)) rows.delete(id);
    }));
    if (el.children[0] !== groupsBox) fill(el, groupsBox);
  }

  function draw() {
    drawNow();
    if (focusTask === null) return;
    const toggle = [...groupsBox.querySelectorAll("[data-key]")].find((n) => n.getAttribute("data-key") === `toggle-${focusTask}`);
    focusTask = null;
    if (toggle && toggle.focus) toggle.focus();
  }

  /** Open the row of the task the route names once, with its group open, and take the focus to it: the destination of a click on an owl. */
  function select(id) {
    if (!Number.isInteger(id) || id === applied) return;
    const task = last.tasks.find((t) => t.id === id);
    if (!task) return;
    applied = id;
    const group = groupTasks(last.tasks).find((g) => g.tasks.some((t) => t.id === id));
    if (group) opened.set(group.id, true);
    expanded.add(id);
    ensure(task);
    focusTask = id;
  }

  return {
    el,
    /** data: {tasks, requests, pending, loading, reload, unaccepted}; reload is the page's stamp, which moves when the store changed; unaccepted: nothing is read (the bodies held stay). */
    update(data) {
      if (data.reload !== undefined) {
        if (reloaded !== null && data.reload !== reloaded) {     // the store changed: every body held is stale, whatever its age
          changes += 1;
          for (const entry of bodies.values()) entry.at = 0;
          for (const card of videos.values()) card.load({ quiet: true });
        }
        reloaded = data.reload;
      }
      last = { tasks: data.tasks || [], requests: data.requests || [], pending: data.pending || [], loading: Boolean(data.loading) };
      for (const [recording, card] of [...videos]) {      // a task that is no longer listed (cancelled, purged) takes its card with it
        if (!last.loading && !last.tasks.some((t) => recordingOf(t) === recording)) {
          card.close();
          videos.delete(recording);
        }
      }
      if (!last.loading) select(data.selected);
      if (!data.unaccepted) read();
      draw();
    },
    /** The tab was left: the next route that names a task opens it again. */
    forget() {
      applied = null;
    },
  };
}
