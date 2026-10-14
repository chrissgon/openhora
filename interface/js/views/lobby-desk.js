// The Lobby's Desk tab (handoff lobby.md, "Desk tab"; R-40, R-47): every document of `artifacts` (C-2: the Lobby is the project's room) as a list of
// two-line rows in the panel's width: the path (a button that opens the viewer) with the agent of the document as a badge at its right, then the owner skill,
// the size and kind and the time. The Floor's viewer shows the document. The page reads `artifacts` (on every reload of the page, and when it is older than 5 seconds while the Desk is open or 30 otherwise) and puts a path in the
// viewer only when the person clicks one; the viewer reads the file with `artifact` and shows it as text, or, for an image, with `artifactRaw` (A-33).

import * as api from "../api.js";
import { createViewer } from "../floor/viewer.js";
import { busyLine, field } from "../floor/widgets.js";
import { fill, h } from "../dom.js";
import { arrowNav } from "../frame/arrows.js";
import { PHONE_QUERY } from "../frame/drawer.js";
import { deskRows, pathParts } from "../floor-model.js";
import * as format from "../format.js";
import { lobbyDocuments } from "./lobby-model.js";

export const NONE_IN_PROJECT = "The project has no documents under docs/ yet.";

const DOCS_OPEN_MS = 5000;
const DOCS_IDLE_MS = 30000;

/** A path as nodes with a `wbr` after each of "/", "-" and ".", so a name is never broken inside a word. */
function pathNodes(path) {
  const out = [];
  for (const part of pathParts(path)) out.push(part, h("wbr"));
  out.pop();
  return out;
}

/** The date and the time of "2026-10-03 09:05" as two parts that are never broken inside. */
function whenParts(text) {
  const [date, ...time] = String(text).split(" ");
  return time.length ? [h("span", { class: "wb-nowrap", text: date }), " ", h("span", { class: "wb-nowrap", text: time.join(" ") })] : [h("span", { class: "wb-nowrap", text: date })];
}

/**
 * The list itself: {el, update({documents, truncated, loading, error}), focusRow(path)}. A row is two lines (R-40): the path and the agent's badge; the owner
 * skill, the size with its kind and the time. A filter works in the page over the rows already read (no request). The agent's badge is the word the frame
 * uses for the agent ("Lobby" for the planning agent, and for a document no agent owns).
 */
function createDeskList(env) {
  const el = h("div", { class: "wb-desk-tab" });
  const input = h("input", { class: "pui-input wb-field-input", type: "text", placeholder: "Path or owner skill", "data-key": "filter" });
  const filterField = field("Filter documents", input);
  const states = h("div", { class: "wb-desk-states" });
  const listBox = h("div", { class: "wb-desk-list-box" });
  fill(el, filterField, states, listBox);
  let last = { documents: [], truncated: false, loading: true, error: null };
  let shown = "";
  input.addEventListener("input", () => draw(true));

  function list(rows) {
    const items = rows.map((r) => {
      const open = h("button", { class: "wb-path-button wb-path-btn mono", type: "button", "data-path": r.path, "aria-label": `Open ${r.path}` }, pathNodes(r.path));
      open.addEventListener("click", (event) => {
        event.stopPropagation();
        env.open(r.path);
      });
      const kind = r.kind ? `${r.size ? " · " : ""}${r.kind}` : "";
      const row = h("li", { class: "wb-desk-row" },
        h("span", { class: "wb-desk-path" }, open,
          r.bound ? h("span", { class: "pui-badge pui-muted pui-soft", title: "bound to a decision" }, "bound", h("span", { class: "wb-sr", text: " to a decision" })) : null),
        h("span", { class: "pui-badge pui-muted pui-soft wb-desk-agent", text: r.agent ? format.agentWord(r.agent) : "Lobby" }),
        h("span", { class: "wb-desk-meta wb-muted" },
          h("span", { class: "mono wb-desk-owner", text: r.owner }), r.owner ? " · " : "", h("span", { class: "wb-nowrap" }, r.size, h("span", { class: "wb-desk-kind", text: kind })), " · ", ...whenParts(r.modified)));
      row.addEventListener("click", () => env.open(r.path));
      return row;
    });
    const node = h("ul", { class: "pui-card wb-desk-list", "aria-label": "Documents of the project, newest first" }, items);
    arrowNav(node, "button.wb-path-button");
    return node;
  }

  function draw(force = false) {
    const text = input.value;
    const rows = deskRows(last.documents, text);
    const key = JSON.stringify([rows, last.truncated, last.loading, last.error, last.documents.length]);
    if (!force && key === shown) return;
    shown = key;
    const active = document.activeElement;
    const path = active && listBox.contains(active) && active.getAttribute ? active.getAttribute("data-path") : null;
    if (last.error) {
      fill(states, h("div", { class: "wb-state-block is-error", role: "alert" }, h("strong", { class: "wb-refusal-title", text: "The documents could not be read" }), h("span", { class: "mono", text: last.error })));
      fill(listBox);
      listBox.hidden = true;
      filterField.hidden = true;
      return;
    }
    if (last.loading) {
      fill(states, h("div", { class: "wb-state-block is-sunken" }, busyLine("Loading the floor...")));
      listBox.hidden = true;
      filterField.hidden = true;
      return;
    }
    if (!last.documents.length && !last.truncated) {
      fill(states, h("div", { class: "wb-state-block is-dashed wb-muted", text: NONE_IN_PROJECT }));
      listBox.hidden = true;
      filterField.hidden = true;
      return;
    }
    filterField.hidden = false;
    fill(states,
      last.truncated ? h("div", { class: "wb-state-block", role: "status", text: "Only the first 2000 files are listed" }) : null,
      !rows.length ? h("div", { class: "wb-state-block is-dashed wb-muted", role: "status", text: "No document matches the filter." }) : null);
    listBox.hidden = !rows.length;
    fill(listBox, rows.length ? list(rows) : null);
    if (path) {
      const next = listBox.querySelectorAll ? [...listBox.querySelectorAll("button.wb-path-button")].find((b) => b.getAttribute("data-path") === path) : null;
      if (next) next.focus({ preventScroll: true });
    }
  }

  return {
    el,
    update(data) {
      last = data;
      draw();
    },
    focusRow(path) {
      const rows = listBox.querySelectorAll ? [...listBox.querySelectorAll("button.wb-path-button")] : [];
      const found = rows.find((b) => b.getAttribute("data-path") === path);
      if (found) found.focus();
    },
  };
}

/**
 * Create the Desk. env: {project, open(path) (the person chose a document), changed() (the documents were read)}. Returns {el, update({tab,
 * ready}), rows() (the planning agent's documents, or null while unread), focusRow(path)}.
 */
export function createLobbyDesk(env) {
  const { project } = env;
  const desk = createDeskList({ open: env.open });
  let documents = null;      // {rows, truncated} as read, or null
  let error = null;
  let at = 0;
  let reading = false;
  let disposed = false;

  async function read() {
    if (reading || disposed) return;
    reading = true;
    try {
      const body = await api.artifacts(project);
      documents = { rows: Array.isArray(body.artifacts) ? body.artifacts : [], truncated: Boolean(body.truncated) };
      error = null;
    } catch (e) {
      // a project that is not accepted yet: the page shows its waiting line; any other failure is shown by the table
      if (!(e && e.name === "ApiError" && e.status === 412)) error = (e && e.message) || "The documents could not be read.";
    }
    at = Date.now();
    reading = false;
    if (!disposed) {
      draw();
      env.changed();
    }
  }

  function draw() {
    const rows = documents ? lobbyDocuments(documents.rows) : [];
    desk.update({ documents: rows, truncated: Boolean(documents && documents.truncated), loading: documents === null && !error, error });
  }

  return {
    el: desk.el,
    /** tab: the selected tab id; ready: the project is read and accepted. */
    update({ tab, ready }) {
      if (ready) {
        const stale = Date.now() - at > (tab === "desk" ? DOCS_OPEN_MS : DOCS_IDLE_MS);
        if (at === 0 || stale) read();
      }
      draw();
    },
    rows() {
      return documents ? lobbyDocuments(documents.rows) : null;
    },
    /** The Desk's row of a file ({path, kind, size, ...}), or undefined while the list is unread or lacks the path. */
    listed(path) {
      return documents ? documents.rows.find((d) => d.path === path) : undefined;
    },
    focusRow(path) {
      desk.focusRow(path);
    },
    /** The store changed: the documents are stale, whatever their age; the next update reads them. */
    reload() {
      at = 0;
    },
    dispose() {
      disposed = true;
    },
  };
}

/**
 * The viewer of a document of the Desk. It takes the whole panel's place (`host` inside the panel), or on a phone a dialog. env: {frame,
 * panel (the element the host goes in), project, onClose(), listed(path) (the Desk's row of a file)}. Returns {show(path) -> "inline" | "dialog" | null, reload(), dispose()}.
 */
export function createLobbyViewer(env) {
  const viewer = createViewer({ onClose: () => env.onClose(), listed: env.listed });
  const host = h("div", { class: "wb-viewer-host", hidden: true }, viewer.el);
  env.panel.append(host);
  const dialog = h("dialog", { class: "pui-modal wb-viewer-dialog", "aria-label": "Document" });
  dialog.addEventListener("close", () => {
    if (current !== null) env.onClose();
  });
  env.frame.el.append(dialog);
  const phone = window.matchMedia(PHONE_QUERY);
  let current = null;

  return {
    /** Show the document at `path`, or none for null. Returns where it is: "inline" (in the panel's place), "dialog" (a phone) or null. */
    show(path) {
      if (path === null || path === undefined) {
        if (current !== null) {
          viewer.close();
          current = null;
          if (dialog.open) dialog.close();
        }
        host.hidden = true;
        return null;
      }
      if (current !== path) {
        current = path;
        viewer.load(env.project, path).then(() => viewer.focus());
      }
      if (phone.matches) {
        if (viewer.el.parentNode !== dialog) dialog.append(viewer.el);
        if (!dialog.open) dialog.showModal();
        host.hidden = true;
        return "dialog";
      }
      if (viewer.el.parentNode !== host) host.append(viewer.el);
      host.hidden = false;
      return "inline";
    },
    /** The store changed: the document that is open is read again, and stays on show until the new text arrives. */
    reload() {
      if (current !== null) viewer.load(env.project, current, { quiet: true });
    },
    dispose() {
      viewer.close();
      current = null;
      host.remove();
      dialog.remove();
    },
  };
}
