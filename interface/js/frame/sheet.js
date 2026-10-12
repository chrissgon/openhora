// The sheet of a phone (OPEN-13): a `dialog.pui-modal` that holds a list (the tracking bar's steps, the waiting list). It
// is modal, closes with Escape or its button, and returns the focus to the control that opened it.

import { h } from "../dom.js";
import { keepFocus } from "./arrows.js";
import { icon } from "./icons.js";

/** Create a sheet host. Returns {el, open(title, body, opener, kind), refill(kind, body), close()}. */
export function createSheet() {
  const heading = h("strong", { class: "wb-sheet-title", text: "" });
  const close = h("button", { class: "pui-btn pui-surface pui-outline wb-sheet-close", type: "button", "aria-label": "Close" }, icon("x", 16));
  const body = h("div", { class: "wb-sheet-body" });
  const card = h("div", { class: "pui-card wb-sheet-card" }, h("div", { class: "wb-sheet-head" }, heading, close), body);
  const el = h("dialog", { class: "pui-modal wb-sheet", "aria-label": "List" }, card);
  let opener = null;
  let kind = null;       // what the open dialog shows ("waiting" for the decisions' list), so that a reload redraws that list and no other
  close.addEventListener("click", () => el.close());
  el.addEventListener("click", (event) => {
    if (event.target === el) el.close();
  });
  el.addEventListener("close", () => {
    if (opener && opener.isConnected) opener.focus();
    opener = null;
    kind = null;
  });
  // A link inside the sheet goes somewhere else on this page: close first.
  body.addEventListener("click", (event) => {
    if (event.target.closest("a")) el.close();
  });
  return {
    el,
    /** `kind` names the list, so that `refill` can find it again while the dialog is open. */
    open(title, content, from, listKind = null) {
      heading.textContent = title;
      el.setAttribute("aria-label", title);
      body.replaceChildren(content);
      opener = from || null;
      kind = listKind;
      if (!el.open) el.showModal();
    },
    /**
     * Draw the list of `listKind` again while it is open (C-22): the focus stays on the link with the same address when that row is still
     * there, else on the first link, else on the close button, so that it never falls out of the modal dialog. Does nothing when the
     * dialog is closed or shows another list.
     */
    refill(listKind, content) {
      if (!el.open || kind !== listKind) return;
      const active = document.activeElement;
      const inside = Boolean(active && body.contains(active));
      keepFocus(body, () => body.replaceChildren(content));
      if (inside && !body.contains(document.activeElement)) {
        const first = body.querySelector("a");
        (first || close).focus();
      }
    },
    close() {
      if (el.open) el.close();
    },
  };
}
