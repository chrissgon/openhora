// F-4 "Waiting for you" (R-7): one card at the bottom right of every screen (open on the City, closed on its header line elsewhere), the inbox
// button of a phone's bottom bar and the list a phone's dialog shows. A row is a link to the card where the decision is answered.

import { h } from "../dom.js";
import { arrowNav, keepFocus } from "./arrows.js";
import { icon } from "./icons.js";

/** The rows as a list of links. state: "ready", "loading" or "error"; rows: model.waitingRows. */
export function rowList(rows, state, { chevron = true } = {}) {
  if (state === "loading") return h("p", { class: "wb-empty", text: "Loading the projects..." });
  if (state === "error" && rows.length === 0) return h("p", { class: "wb-empty", text: "The decisions could not be read." });
  if (rows.length === 0) return h("p", { class: "wb-empty", text: "Nothing waits for you." });
  const list = h("ul", { class: "pui-list pui-hoverable wb-wait-list" }, rows.map((row) => h("li", { class: "pui-list-item wb-wait-item" },
    h("a", { class: `wb-wait-row${chevron ? "" : " no-chevron"}`, href: row.link, "aria-label": row.name },
      h("span", { class: "pui-badge pui-warn pui-soft wb-wait-kind", text: row.kind }),
      h("span", { class: "wb-wait-title", text: row.title }),
      h("span", { class: "wb-wait-where", text: row.where }),
      h("span", { class: "wb-wait-age", text: row.age }),
      chevron ? h("span", { class: "wb-wait-chev" }, icon("chevron-right", 14)) : null))));
  arrowNav(list, ".wb-wait-row");
  return list;
}

/**
 * The card's header (R-7): a warn tile, the title and the count. On a project's screens the header is a button with a chevron (up while the
 * card is closed, down while it is open): the card is closed on its header line and opens upward. On the City the card is open and the header
 * is plain.
 */
function head(count, { collapsible, open, onToggle }) {
  const parts = [
    h("span", { class: "wb-kpi-tile pui-soft pui-warn" }, icon("inbox", 16)),
    h("strong", { class: "wb-wait-heading", text: "Waiting for you" }),
    // F2-D9: with nothing waiting the card says so in a muted word instead of a "0" chip; the count chip stays for one or more, and "..." while it is read
    count === 0 ? h("span", { class: "wb-wait-none", text: "nothing waits" }) : h("span", { class: "pui-badge pui-warn pui-soft pui-rounded-full", text: String(count) }),
  ];
  if (!collapsible) return h("div", { class: "wb-wait-head" }, parts);
  parts.push(h("span", { class: "wb-wait-up", "aria-hidden": "true" }, icon(open ? "chevron-down" : "chevron-up", 16)));
  const button = h("button", { class: "wb-wait-head wb-wait-toggle", type: "button", "aria-expanded": String(open) }, parts);
  button.addEventListener("click", onToggle);
  return button;
}

/**
 * The card at the bottom right of every screen (R-7). Returns {el, set(rows, state), setCollapsible(on), isOpen(), close(), destroy()}. On the City it is open
 * and has no toggle; on a project's screens (`setCollapsible(true)`) it starts closed on its header line and a click opens it upward; Escape, a click
 * outside it and a change of screen close it.
 */
export function createWaitingCard({ onOpen = () => {} } = {}) {
  const body = h("div", { class: "wb-wait-body" });
  const el = h("section", { class: "pui-card wb-waiting", role: "region", "aria-label": "Waiting for you, loading", id: "wb-panel", tabindex: "-1" }, body);
  let last = { rows: [], state: "loading" };
  let collapsible = false;
  let open = true;
  let shown = "";
  let toggleButton = null;       // the header, while the card has a toggle
  const isOpen = () => collapsible && open;
  function draw() {
    const key = JSON.stringify([last, collapsible, open]);
    if (key === shown) return;
    shown = key;
    const { rows, state } = last;
    el.setAttribute("aria-label", state === "loading" ? "Waiting for you, loading" : `Waiting for you, ${rows.length} decision${rows.length === 1 ? "" : "s"}`);
    el.classList.toggle("is-collapsible", collapsible);
    el.classList.toggle("is-collapsed", collapsible && !open);
    el.classList.toggle("is-open", !collapsible || open);
    if (collapsible) el.removeAttribute("id"); else el.setAttribute("id", "wb-panel");     // the City's card is the panel the skip link names; elsewhere the panel is
    const count = state === "loading" ? "..." : rows.length;
    const toggle = () => {
      open = !open;
      if (open) onOpen();
      draw();
      if (toggleButton) toggleButton.focus();
    };
    const header = head(count, { collapsible, open, onToggle: toggle });
    toggleButton = collapsible ? header : null;
    keepFocus(body, () => body.replaceChildren(header, ...(collapsible && !open ? [] : [rowList(rows, state)])));
  }
  const onPointerDown = (event) => {
    if (isOpen() && !el.contains(event.target)) {
      open = false;
      draw();
    }
  };
  document.addEventListener("pointerdown", onPointerDown);
  el.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !isOpen()) return;
    event.stopPropagation();     // the page's one Escape handler must not go up as well
    open = false;
    draw();
    if (toggleButton) toggleButton.focus();
  });
  return {
    el,
    destroy() { document.removeEventListener("pointerdown", onPointerDown); },
    isOpen,
    close() {
      if (!isOpen()) return;
      open = false;
      draw();
    },
    /** A project's screen: closed on its header line. The City: open, no toggle. A change of this word closes the card. */
    setCollapsible(on) {
      if (collapsible === Boolean(on)) return;
      collapsible = Boolean(on);
      open = !collapsible;
      draw();
    },
    set(rows, state) {
      last = { rows, state };
      draw();
    },
  };
}

/**
 * The inbox button of a phone's bottom bar (R-7, R-10): the icon and the count, on every screen. It opens the rows in the list dialog; it is not
 * drawn above a phone's width. Returns {el, set(rows, state), close(), button, isOpen(), destroy()}. `onSheet(title, body, opener)` opens the phone's
 * list dialog; `onRefill(body)` draws that dialog's list again while it is open (C-22).
 */
export function createWaitingMenu({ onOpen, onSheet, onRefill = () => {} }) {
  const count = h("span", { class: "pui-badge pui-warn pui-soft pui-rounded-full wb-wait-count", text: "..." });
  const button = h("button", { class: "pui-btn pui-surface pui-outline wb-wait-btn", type: "button", "aria-haspopup": "dialog" }, icon("inbox", 16), count);
  const el = h("div", { class: "wb-wait-menu-wrap" }, button);
  let last = { rows: [], state: "loading" };
  let shownMenu = "";
  button.addEventListener("click", () => {
    onOpen();
    onSheet("Waiting for you", rowList(last.rows, last.state), button);
  });
  return {
    el, button,
    destroy() {},
    close() {},
    isOpen: () => false,
    set(rows, state) {
      const key = JSON.stringify([rows, state]);
      if (key === shownMenu) return;
      shownMenu = key;
      last = { rows, state };
      count.textContent = state === "loading" ? "..." : String(rows.length);
      button.setAttribute("aria-label", state === "loading" ? "Waiting for you, loading" : `Waiting for you, ${rows.length} decision${rows.length === 1 ? "" : "s"}`);
      onRefill(rowList(rows, state));      // a phone's open dialog follows the reload: a resolved row leaves it
    },
  };
}
