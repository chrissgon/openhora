// The Lobby panel's tab list (R-43): a segmented control that fills the panel's width in equal parts, in the regular weight: Conversation, Inbox with a
// count, Tasks, Desk, Agent. The URL names the tab, so a tab is a button that sets the hash; Left and Right move to the next tab, Home and End jump to
// the first and the last. The list stands in a bar (`bar`) with a line under it, which the screen hides with the list when a document takes the panel.

import { h } from "../dom.js";
import * as router from "../router.js";
import { TABS } from "./lobby-model.js";

/** Create the tab list. Returns {el, bar, set({project, selected, counts}), setHidden(on), panelId(id), tabId(id)}. */
export function createTabs() {
  const el = h("div", { class: "wb-lobby-tabs", role: "tablist", "aria-label": "Lobby" });
  const bar = h("div", { class: "wb-lobby-tabbar" }, el);
  const buttons = new Map();
  let project = null;
  let shownTab = null;
  /** On a narrow phone the tab list scrolls (320 px): the selected tab is brought into view, sideways only. */
  function keepInView(button) {
    if (typeof button.getBoundingClientRect !== "function") return;
    const b = button.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    if (b.left < r.left) el.scrollLeft -= r.left - b.left + 8;
    else if (b.right > r.right) el.scrollLeft += b.right - r.right + 8;
  }
  const panelId = (id) => `wb-lobby-panel-${id}`;
  const tabId = (id) => `wb-lobby-tab-${id}`;

  for (const [id, label] of TABS) {
    const count = h("span", { class: "pui-badge pui-warn pui-soft pui-rounded-full wb-lobby-tab-count", hidden: true, text: "" });
    const button = h("button", { class: "wb-lobby-tab", type: "button", role: "tab", id: tabId(id), "aria-controls": panelId(id), tabindex: "-1" },
      h("span", { text: label }), count);
    button.addEventListener("click", () => {
      if (project) window.location.hash = router.lobbyHash(project, id);
    });
    buttons.set(id, { button, count, label });
    el.append(button);
  }
  el.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const ids = TABS.map(([id]) => id);
    const at = ids.findIndex((id) => buttons.get(id).button === document.activeElement);
    let next = at < 0 ? 0 : at;
    if (event.key === "ArrowRight") next = (at + 1) % ids.length;
    else if (event.key === "ArrowLeft") next = (at - 1 + ids.length) % ids.length;
    else if (event.key === "Home") next = 0;
    else next = ids.length - 1;
    event.preventDefault();
    buttons.get(ids[next]).button.focus();
    if (project) window.location.hash = router.lobbyHash(project, ids[next]);
  });

  // a tab that grows (a count arrives) or a panel that gets its width late moves the selected tab: it is brought back into view
  if (typeof ResizeObserver === "function") {
    const watch = new ResizeObserver(() => { const on = el.querySelector('[aria-selected="true"]'); if (on) keepInView(on); });
    for (const { button } of buttons.values()) watch.observe(button);
    watch.observe(el);
  }

  return {
    el,
    bar,
    panelId,
    tabId,
    setHidden(on) {
      bar.hidden = Boolean(on);
      el.hidden = Boolean(on);
    },
    /** counts: {inbox: n}; a count of 0 is not drawn. */
    set({ project: id, selected, counts }) {
      project = id;
      for (const [name, { button, count, label }] of buttons) {
        const on = name === selected;
        button.setAttribute("aria-selected", on ? "true" : "false");
        button.tabIndex = on ? 0 : -1;
        button.classList.toggle("is-selected", on);
        if (on && name !== shownTab) {
          shownTab = name;
          keepInView(button);
        }
        const n = counts && counts[name] ? counts[name] : 0;
        count.hidden = n <= 0;
        count.textContent = String(n);
        button.setAttribute("aria-label", n > 0 ? `${label}, ${n} waiting` : label);
      }
    },
  };
}
