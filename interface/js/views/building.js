// The Building screen (round 4: building.html, R-25 to R-29): the cutaway of a project, one floor per area agent from the lobby up, a plate beside
// each floor (name row and the two meters of the day), and in the panel (380 px) the project's name with Project state as an icon button, its facts,
// `Requests (n)` (a row each, with `Cancel request`), `Documents (n)` and `Floors`, the HTML twin of the scene. A floor is one thing in three places
// (R-28): a pointer or the focus on the room, on its plate or on its row marks the three. On a phone one floor card hangs at the bottom left of the
// scene and two buttons step through the floors. It owns the scene engine for as long as the screen is shown. What the frame holds (the top row, the
// KPI cards, the tracking bar) is filled by the page; this fills the scene and the panel. It reads: `artifacts` (the Documents count and each floor's
// bookcase) and, for "Project state", one file under docs/. Its one write is `cancel`, from a request's row, after the confirmation dialog.

import * as api from "../api.js";
import { fill, h } from "../dom.js";
import * as fm from "../floor-model.js";
import { createViewer } from "../floor/viewer.js";
import { chip } from "../floor/widgets.js";
import { arrowNav, keepFocus } from "../frame/arrows.js";
import { bindDrawer, createGrip } from "../frame/drawer.js";
import { icon } from "../frame/icons.js";
import { acceptance } from "../model.js";
import * as router from "../router.js";
import { NoWebGL } from "../scene/engine.js";
import { floorCardNode, rowNode } from "../scene/plates.js";
import { worldModel } from "../world-model.js";
import { cancelCount } from "./lobby-model.js";
import { createCancelDialog } from "./lobby-request.js";

export const PLATE_GAP_X = 14;
export const PLATE_SHIFT = 28;     // the plates stand this far from the column the scene puts them in (css/building.css: `.wb-plate { margin-left }`), where building.html draws them
const PHONE_LEVEL = 16;       // the camera buttons stand at least this far from the scene's bottom edge (scene/engine.js)
const PHONE_TOOLS_H = 44;     // their height and the gap above them: the floor card hangs from there
const STATE_PATH = "docs/workbench/state.md";
const ARTIFACTS_EVERY_MS = 20000;

/** Create the Building in `frame`. env: {refresh()}. Returns {update({snapshot, route, now, reload}), dispose(), stats()}. */
export function createBuildingView(frame, env) {
  let engine = null;
  let disposed = false;
  let last = null;
  let documents = null;
  let documentsTruncated = false;
  let documentsAt = 0;
  let reading = false;
  let hover = null;          // the floor marked now: the pointer's, else the focus's
  let pointerAt = null;      // two slots, so that a pointer leaving a focused row does not clear the keyboard's mark
  let focusAt = null;
  let focusName = null;
  let shown = "";
  let listShown = "";
  let projectId = null;
  let reloaded = null;   // the page's reload stamp last seen: when it moves the store changed, and the documents are read again

  // --- the panel ---------------------------------------------------------------------------------------------------------------
  const title = h("strong", { class: "wb-panel-title", id: "wb-building-title", text: "" });
  const panelSub = h("span", { class: "wb-panel-sub", text: "Project · one floor per area agent" });
  // R-27: Project state is an icon button at the right of the head (information, soft, muted); it opens the viewer on docs/workbench/state.md
  const stateButton = h("button", { class: "pui-btn pui-soft pui-muted wb-state-btn", type: "button", "aria-label": "Project state", title: "Project state" }, icon("info", 16));
  const head = h("div", { class: "wb-panel-head" },
    h("span", { class: "wb-tile pui-soft pui-theme" }, icon("building-2", 18)), h("div", { class: "wb-panel-titles" }, title, panelSub), stateButton);
  const factsBox = h("dl", { class: "wb-facts" });
  const loadingLine = h("p", { class: "wb-muted", text: "Loading the floors...", hidden: true });
  const requestsHeading = h("h3", { class: "wb-sec-head" });
  const requestsList = h("ul", { class: "wb-rq-list", "aria-label": "Open requests" });
  const requestsEmpty = h("p", { class: "wb-muted wb-sec-empty", text: "No request is open", hidden: true });
  const requestsSection = h("section", { class: "wb-sec", hidden: true }, requestsHeading, requestsEmpty, requestsList);
  const docsCount = h("span", { class: "wb-muted" });
  const docsLink = h("a", { class: "wb-docs-link", href: "#" }, icon("file-text", 16), h("strong", { text: "Documents" }), " ", docsCount, h("span", { class: "wb-fl-chev" }, icon("chevron-right", 14)));
  const docsSection = h("section", { class: "wb-sec wb-docs", hidden: true }, docsLink);
  const listHeading = h("h3", { class: "wb-sec-head", text: "Floors" });
  const list = h("ul", { class: "wb-fl-list", "aria-label": "Floors, top to bottom" });
  const moreLine = h("p", { class: "wb-muted wb-sec-empty", hidden: true });
  const noneLine = h("p", { class: "wb-muted wb-sec-empty", text: "This project has no area agents in its configuration.", hidden: true });
  const floorSection = h("section", { id: "wb-scene-list", tabindex: "-1", class: "wb-sec", hidden: true }, listHeading, moreLine, list, noneLine);
  const body = h("div", { class: "wb-panel-body" }, loadingLine, factsBox, requestsSection, docsSection, floorSection);
  const grip = createGrip();
  const panel = h("section", { class: "pui-card wb-panel wb-drawer wb-panel-building wb-bpanel", role: "region", "aria-labelledby": "wb-building-title", id: "wb-panel", tabindex: "-1" }, grip, head, body);
  const drawer = bindDrawer(panel, { screen: "building", grip });
  frame.main.append(panel);
  arrowNav(list, "a.wb-fl-row");
  arrowNav(requestsList, "button.wb-rq-main");

  // the project state file, in a dialog with the same viewer the Floor uses
  const stateDialog = h("dialog", { class: "pui-modal wb-viewer-dialog", "aria-label": "Project state" });
  const viewer = createViewer({ onClose: () => stateDialog.close() });
  stateDialog.append(viewer.el);
  stateDialog.addEventListener("close", () => {
    viewer.close();
    if (stateButton.isConnected) stateButton.focus();
  });
  stateDialog.addEventListener("click", (event) => {
    if (event.target === stateDialog) stateDialog.close();
  });
  frame.el.append(stateDialog);
  stateButton.addEventListener("click", () => {
    if (!projectId) return;
    stateDialog.showModal();
    viewer.load(projectId, STATE_PATH);
    viewer.focus();
  });

  // R-27, C-2: `Cancel request` on a request's row opens the Lobby's own confirmation dialog, kept as built; the page reloads when the request is cancelled
  let cancelDialog = null;
  function askCancel(request, opener) {
    if (!projectId) return;
    if (!cancelDialog) {
      cancelDialog = createCancelDialog({ api, project: projectId, onChanged: async () => { if (env && env.refresh) await env.refresh(); } });
      frame.el.append(cancelDialog.el);
      cancelDialog.el.addEventListener("close", () => { if (cancelOpener && cancelOpener.isConnected) cancelOpener.focus(); });
    }
    cancelOpener = opener;
    cancelDialog.open(request, cancelCount(request));
  }
  let cancelOpener = null;

  // the phone's floor buttons and counter, over the scene
  const above = h("button", { class: "pui-btn pui-surface pui-outline wb-floor-step", type: "button", "aria-label": "Floor above" }, icon("chevron-down", 16));
  above.classList.add("is-above");
  const below = h("button", { class: "pui-btn pui-surface pui-outline wb-floor-step", type: "button", "aria-label": "Floor below" }, icon("chevron-down", 16));
  const counter = h("span", { class: "wb-floor-counter", "aria-live": "polite" });
  const steps = h("div", { class: "wb-floor-steps" }, above, counter, below);
  const sceneArea = frame.sceneHost.parentElement || frame.sceneHost;
  sceneArea.append(steps);

  // --- the scene -----------------------------------------------------------------------------------------------------------------
  function open(id) {
    if (disposed || !last) return;
    if (id === "door") {
      window.location.hash = router.controlHash(projectId);
      return;
    }
    const name = String(id).replace(/^floor:/, "");
    const view = fm.building(last.snapshot, projectId);
    const row = view && view.rows.find((r) => r.name === name);
    if (!row) return;
    // The floor goes on as the click lands: the other floors shrink while the camera closes on it, and the route changes in the same moment.
    if (engine) engine.flyTo(id);
    window.location.hash = row.link;
  }

  // R-28: a floor is one thing in three places, the room in the scene, its plate and its row. A pointer or the focus on any of them marks the three: the scene
  // draws corner brackets on the room (`engine.highlight`), the plate and the row take the brand outline (`is-hover`). `fromScene`: the scene itself is the one
  // hovered (its own pick already drew the brackets): the engine is not told again, or a hover of the door (not a floor, so name is null here) would clear
  // the mark the scene just drew.
  function markFloor(name) {
    const places = [...(frame.sceneHost.querySelectorAll ? frame.sceneHost.querySelectorAll(".wb-plate") : []), ...(list.querySelectorAll ? list.querySelectorAll(".wb-fl-row") : [])];
    for (const el of places) el.classList.toggle("is-hover", name !== null && el.getAttribute("data-floor") === name);
  }

  // `source` "pointer" or "keyboard" fills its own slot; "clear" (the engine's Escape) empties both. The mark is the pointer's floor, else the focus's.
  function highlightRow(name, fromScene = false, source = "pointer") {
    if (source === "clear") { pointerAt = null; focusAt = null; } else if (source === "keyboard") focusAt = name; else pointerAt = name;
    hover = pointerAt || focusAt;
    markFloor(hover);
    // the engine is told unless the scene itself drew exactly this (its own pick already did): a pointer that leaves the room while the focus is on a row puts the focus's brackets back
    if (engine && (!fromScene || hover !== name)) engine.highlight(hover ? `floor:${hover}` : null, pointerAt ? "pointer" : "keyboard");
    drawCorner();
  }

  // The phone's floor card at the scene's top right: the floor the pointer or the focus is on (the phone shows one floor at a time).
  // Desktop and tablet keep the plates beside the floors (WP-9.10), so there is no card there. The same component as each row of the floors list.
  let cornerKey = "";
  function drawCorner() {
    if (!engine || !last) return;
    const view = fm.building(last.snapshot, projectId);
    let row = null;
    if (phone.matches && view && last.snapshot.loaded) {
      const wanted = hover || focusOf(view);
      row = view.rows.slice(0, 8).find((r) => r.name === wanted) || null;
    }
    const card = row ? fm.cardOf(row) : null;
    const key = JSON.stringify(card);
    if (key === cornerKey) return;
    cornerKey = key;
    engine.setCorner(card ? floorCardNode(card, { class: "is-corner", "aria-hidden": "true" }) : null);
  }

  try {
    engine = frame.acquireWorld({
      label: "Building, loading",
      getInsets: (about) => {
        const base = frame.insets(panel, { notice: !(about && about.dim) });   // building.html: the band over a project that is not accepted floats over the tower, which keeps its size
        if (frame.isPhone()) {
          // The floor card hangs bottom left above the camera buttons (A-28); the floor steps stand at the right, level with those buttons.
          const level = Math.max(PHONE_LEVEL, base.bottom);
          steps.style.setProperty("--wb-y", `${level}px`);
          return { left: 4, right: 70, top: base.top, bottom: base.bottom, pad: 0.98, cornerRight: 10, cornerLeft: 10, cornerBottom: level + PHONE_TOOLS_H };
        }
        return { ...base, right: base.right + frame.plateWidth() + PLATE_GAP_X + PLATE_SHIFT, plateRight: base.right + PLATE_SHIFT };
      },
      onOpen: open,
      onHover: (id, how) => highlightRow(id && String(id).startsWith("floor:") ? String(id).slice(6) : null, true, how === "clear" ? "clear" : "pointer"),
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
  observer.observe(frame.kpis.el);
  observer.observe(panel);
  observer.observe(frame.noticeBox);
  const phone = window.matchMedia("(max-width: 639px)");
  const onPhone = () => { shown = ""; redraw(); };
  phone.addEventListener("change", onPhone);

  // plates in the overlay are pointer targets: hovering one outlines its floor, a click opens it
  const overPlate = (event) => (event.target && event.target.closest ? event.target.closest(".wb-plate") : null);
  const onOver = (event) => {
    const plate = overPlate(event);
    if (plate) highlightRow(plate.getAttribute("data-floor"));
  };
  const onOut = (event) => {
    if (overPlate(event)) highlightRow(null);
  };
  const onClick = (event) => {
    const plate = overPlate(event);
    if (plate) open(`floor:${plate.getAttribute("data-floor")}`);
  };
  frame.sceneHost.addEventListener("pointerover", onOver);
  frame.sceneHost.addEventListener("pointerout", onOut);
  frame.sceneHost.addEventListener("click", onClick);

  // --- reading the documents ------------------------------------------------------------------------------------------------------
  async function readDocuments() {
    if (reading || disposed || !projectId) return;
    reading = true;
    try {
      const body = await api.artifacts(projectId);
      documents = Array.isArray(body.artifacts) ? body.artifacts : [];
      documentsTruncated = Boolean(body.truncated);
      documentsAt = Date.now();
      shown = "";
      redraw();
    } catch (e) {
      documentsAt = Date.now();
      if (!documents) documents = [];
    }
    reading = false;
  }

  // the live region says when an agent starts working ("Engineering agent started working"), never on the first read
  const worked = new Map();
  function announceWork(view) {
    for (const row of view.rows) {
      const was = worked.get(row.name);
      if (was === false && row.state === "working") frame.announce(`${row.label} agent started working`);
      worked.set(row.name, row.state === "working");
    }
  }

  // --- drawing -------------------------------------------------------------------------------------------------------------------
  function factRow(label, value, links = false) {
    return [h("dt", { text: label }), h("dd", { class: links ? "wb-facts-links" : null }, value)];
  }

  // R-27 (C-2): the panel keeps Configuration and Running now; the request followed and the decisions count are the selected row and the KPI card
  function drawFacts(view) {
    const f = view.facts;
    const running = f.running ? h("a", { href: f.running.link, text: `task #${f.running.id}${f.running.title ? ` · ${f.running.title}` : ""}` }) : h("span", { class: "wb-muted", text: "Nothing is running" });
    fill(factsBox,
      factRow("Configuration", chip(f.configuration, f.accepted ? "pui-success pui-soft" : "pui-warn pui-soft")),
      f.accepted || f.kept ? factRow("Running now", running, true) : null);
  }

  /** The rows of `Requests (n)`: the number, the title and the state chip, the steps line, the chevron to the request's line in the Lobby, `Cancel request` on a line of its own. */
  function requestItem(r) {
    const main = h("button", { class: "wb-rq-main", type: "button", "data-request": String(r.id), "aria-current": r.selected ? "true" : null, "aria-label": r.name },
      h("span", { class: "pui-badge pui-muted pui-soft wb-rq-n", text: `#${r.id}` }),
      h("strong", { class: "wb-rq-title", text: r.title }),
      r.state ? h("span", { class: `pui-chip ${r.tone} wb-chip-12`, text: r.state }) : null,
      h("span", { class: "wb-rq-sub", text: r.steps }));
    main.addEventListener("click", () => {
      if (env && env.selectRequest && projectId) env.selectRequest(projectId, r.id);   // the tracking bar follows this request (kept in memory), then a redraw and a reload
    });
    const open = h("a", { class: "pui-btn pui-surface pui-outline wb-rq-open", href: r.link, "aria-label": `Open request #${r.id} in the Lobby conversation` }, icon("chevron-right", 14));
    const cancel = r.cancellable
      ? h("button", { class: "pui-btn pui-link pui-error wb-rq-cancel", type: "button", "data-request": String(r.id), "aria-label": `Cancel request ${r.id}`, text: "Cancel request" }) : null;
    if (cancel) cancel.addEventListener("click", () => askCancel(r.request, cancel));
    return h("li", { class: `wb-rq${r.selected ? " is-selected" : ""}`, "data-request": String(r.id) }, main, open, cancel);
  }

  let requestsShown = "";
  function drawRequests(view, status) {
    const shown = Boolean(status) && view.loaded && (view.accepted || view.kept);   // absent until the status is read, and for a project never read that refuses
    requestsSection.hidden = !shown;
    if (!shown) {
      requestsShown = "";
      return;
    }
    const rows = fm.requestRows(status, projectId);
    const sig = JSON.stringify(rows.map((r) => [r.id, r.title, r.state, r.steps, r.selected, r.cancellable]));
    requestsHeading.replaceChildren("Requests ", h("span", { class: "wb-muted", text: `(${rows.length})` }));
    requestsEmpty.hidden = rows.length > 0;
    requestsList.hidden = rows.length === 0;
    if (sig === requestsShown) return;
    requestsShown = sig;
    const active = document.activeElement;
    const kept = active && requestsList.contains(active) && active.getAttribute ? [active.getAttribute("data-request"), active.className] : null;
    requestsList.replaceChildren(...rows.map(requestItem));
    if (kept) {
      const again = [...requestsList.querySelectorAll("button, a")].find((el) => el.getAttribute("data-request") === kept[0] && el.className === kept[1]);
      if (again) again.focus({ preventScroll: true });
    }
  }

  /** `Documents (n)` across the full width: it goes to the Lobby's Desk, which lists every document of the project. Absent until the read answers. */
  function drawDocuments(view) {
    const shown = documents !== null && (view.accepted || view.kept);
    docsSection.hidden = !shown;
    if (!shown) return;
    docsLink.setAttribute("href", router.lobbyDeskHash(projectId));
    docsCount.textContent = `(${documents.length}${documentsTruncated ? "+" : ""})`;
  }

  function floorItem(row, view) {
    // the row is the floor's plate as a list line: the same facts, the chips under the name row (the plate has none)
    const link = rowNode(fm.plateOf(row, view.tag ? view.tag.floor === row.name : false), { href: row.link, "aria-label": row.linkName });
    link.addEventListener("click", (event) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
      event.preventDefault();
      open(`floor:${row.name}`);
    });
    link.addEventListener("pointerenter", () => highlightRow(row.name));
    link.addEventListener("pointerleave", () => highlightRow(null));
    link.addEventListener("focus", () => highlightRow(row.name, false, "keyboard"));
    link.addEventListener("blur", () => highlightRow(null, false, "keyboard"));
    return h("li", { class: "wb-fl-item", "data-floor": row.name }, link);
  }

  function drawList(view) {
    const rows = [...view.rows].reverse().map((row) => floorItem(row, view));
    keepFocus(list, () => list.replaceChildren(...rows));
    markFloor(hover);
    moreLine.hidden = !(view.more > 0);
    if (view.more > 0) moreLine.textContent = `+${view.more} more floor${view.more === 1 ? "" : "s"}`;
    noneLine.hidden = !view.none;
  }

  /** The floor drawn alone on a phone: the one the person chose, else the work order's, else the first with a decision, else the top. */
  function focusOf(view) {
    const names = view.rows.slice(0, 8).map((r) => r.name);
    if (focusName && names.includes(focusName)) return focusName;
    if (view.tag && names.includes(view.tag.floor)) return view.tag.floor;
    const waiting = [...view.rows].reverse().find((r) => r.decisions > 0 || r.state === "working");
    return (waiting || view.rows[view.rows.length - 1]).name;
  }

  function stepFloor(delta, view) {
    const names = view.rows.slice(0, 8).map((r) => r.name);
    const at = names.indexOf(focusOf(view));
    const next = Math.max(0, Math.min(names.length - 1, at + delta));
    focusName = names[next];
    shown = "";
    redraw();
  }

  function redraw() {
    if (disposed || !last) return;
    const { snapshot } = last;
    const view = fm.building(snapshot, projectId);
    const loading = !snapshot.loaded || !view;
    // the hash names a project the service does not hold (the band says so): building.html draws no panel and an empty scene
    const unknown = snapshot.loaded && !view;
    panel.hidden = unknown;
    title.textContent = view ? view.name : "";
    steps.hidden = true;
    loadingLine.hidden = !loading;
    if (!loading) {
      title.textContent = view.name;
      drawFacts(view);
      const detail = snapshot.details[projectId];
      drawRequests(view, detail && detail.status ? detail.status : null);
      drawDocuments(view);
      floorSection.hidden = false;
      const sig = JSON.stringify([view.rows.map((r) => [fm.plateOf(r, false), r.link, r.linkName]), view.more, view.none]);
      if (sig !== listShown) {
        listShown = sig;
        drawList(view);
      }
    } else {
      fill(factsBox);
      requestsSection.hidden = true;
      docsSection.hidden = true;
      floorSection.hidden = true;
      requestsShown = "";
      listShown = "";
    }
    if (!engine) return;
    if (unknown) {
      const empty = worldModel({ ...snapshot, projects: [] }, last.now, { ready: true });
      const emptyKey = JSON.stringify([empty, "Building"]);
      if (emptyKey !== shown) {
        shown = emptyKey;
        engine.show("world", empty, "Building");
      }
      return;
    }
    let label = "Building, loading";
    let frameFloor = null;
    if (!loading) {
      const isPhone = phone.matches;
      frameFloor = isPhone ? focusOf(view) : null;
      label = fm.buildingLabel(view);
      if (isPhone) {
        const names = view.rows.slice(0, 8).map((r) => r.name);
        const at = names.indexOf(frameFloor);
        const row = view.rows.find((r) => r.name === frameFloor);
        steps.hidden = names.length < 2;
        above.disabled = at >= names.length - 1;
        below.disabled = at <= 0;
        counter.textContent = `${at + 1}/${names.length}`;
        counter.setAttribute("aria-label", `Floor ${at + 1} of ${names.length}, ${row ? row.label : ""}`);
        above.onclick = () => stepFloor(1, view);
        below.onclick = () => stepFloor(-1, view);
      }
    }
    const model = worldModel(snapshot, last.now, { selectedId: projectId, focus: projectId, frame: frameFloor, documents, ready: !loading });
    if (!loading) announceWork(view);
    drawCorner();
    const key = JSON.stringify([model, label]);
    if (key !== shown) {
      shown = key;
      engine.show("world", model, label);
      markFloor(hover);   // the plates were made again: the one under the pointer keeps its mark
    }
  }

  return {
    /** data: {snapshot, route, now}. */
    update(data) {
      last = data;
      projectId = data.route.project;
      if (reloaded !== null && data.reload !== reloaded) documentsAt = 0;
      reloaded = data.reload;
      const listed = (data.snapshot.projects || []).find((p) => p.id === projectId);
      const kept = Boolean(listed) && acceptance(listed, data.snapshot.details[projectId]).kept;
      if (!kept && (documents === null || Date.now() - documentsAt > ARTIFACTS_EVERY_MS)) readDocuments();     // a refusing project is not asked again
      redraw();
    },
    dispose() {
      disposed = true;
      observer.disconnect();
      drawer.destroy();   // before the panel leaves the page: the frame hears that nothing covers the scene
      phone.removeEventListener("change", onPhone);
      frame.sceneHost.removeEventListener("pointerover", onOver);
      frame.sceneHost.removeEventListener("pointerout", onOut);
      frame.sceneHost.removeEventListener("click", onClick);
      viewer.close();
      if (cancelDialog) cancelDialog.el.remove();   // the dialog it added to the frame leaves with the view (an open one is dismissed)
      panel.remove();   // the scene is the frame's: the City takes it over (the building closes), or the frame takes it down
      stateDialog.remove();
      steps.remove();
      frame.sceneUnavailable(false);
    },
    /** For the page's checks: the engine's counters, or null without WebGL. */
    stats() {
      return engine ? engine.stats() : null;
    },
  };
}
