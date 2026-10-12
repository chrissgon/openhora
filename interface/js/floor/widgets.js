// Small pieces the Floor's panel and its cards share: the busy ring, a notice, a state chip, a field, the words of an error
// and the tab list. Everything built here is made with h(): text goes in as text, nothing takes markup.

import { fill, h } from "../dom.js";

/** The busy ring (DEVIATION-15): static, hidden from a screen reader; the words carry the state. */
export function ring(small = false) {
  return h("span", { class: `wb-ring${small ? " is-small" : ""}`, "aria-hidden": "true" });
}

/** A line with the ring and its words ("Loading the floor..."), `aria-busy` set. */
export function busyLine(text) {
  return h("div", { class: "wb-busy", "aria-busy": "true", role: "status" }, ring(), h("span", { text }));
}

/** A state chip: tone is the classes ("pui-theme pui-soft"). */
export function chip(text, tone, size = "12") {
  return h("span", { class: `pui-chip ${tone} wb-chip-${size}`, text });
}

/**
 * A notice (R-11): the library's soft style in the state's colour, a tint and no line round it. kind "error" has role alert and the error colour, "warn" role status and the warn
 * colour, any other the muted soft style. The old classes `wb-notice-card is-error|is-warn` stay beside the new ones.
 */
export function notice(text, kind = "info", ...extra) {
  const role = kind === "error" ? "alert" : kind === "warn" ? "status" : null;
  const tone = kind === "error" ? "pui-error" : kind === "warn" ? "pui-warn" : "pui-muted";
  return h("div", { class: `notice pui-soft ${tone} wb-notice-card${kind === "error" ? " is-error" : kind === "warn" ? " is-warn" : ""}`, role }, h("span", { text }), ...extra);
}

/**
 * Give the focus to the "Open <path>" link of the tab drawn in `root`, as soon as the tab has drawn it (a moment later, for a tab that reads
 * first): the person closed a document and expects to be where the link was. Gives up after about three seconds.
 */
export function focusOpenLink(root, path, tries = 30) {
  const label = `Open ${path}`;
  const attempt = (left) => {
    const link = root.querySelectorAll ? [...root.querySelectorAll("a")].find((a) => a.getAttribute("aria-label") === label) : null;
    if (link) link.focus();
    else if (left > 0) setTimeout(() => attempt(left - 1), 100);
  };
  setTimeout(() => attempt(tries), 0);
}

/** A labelled field group: the label's text, then the control. */
export function field(label, control, hint) {
  return h("label", { class: "pui-field-group wb-field" }, h("span", { class: "wb-field-label", text: label }), control, hint || null);
}

/** What the person reads when a request failed (the frame's texts and the flows' failure branches). */
export function errorText(e) {
  if (!e) return "The request failed.";
  if (e.name === "ApiError") {
    if (e.status === 0) return "The service could not be reached. Is it still running?";
    if (e.status === 409 && e.word === "busy") return "A model run is already going for this project. Nothing was started; try again when it ends.";
    if (e.status === 404) return "That item is not there any more.";
    if (e.status === 500) return "The service had an internal error. The details are in its terminal.";
    if (e.status === 503) return "The service is stopping.";
    return e.message || e.word || "The request failed.";
  }
  return e.message || "The request failed.";
}

/** True when the failure means the item is gone (404): the card is removed. */
export function isGone(e) {
  return Boolean(e && e.name === "ApiError" && e.status === 404);
}

/** The message of a job that failed, or the generic one. */
export function jobText(job) {
  const error = job && job.error;
  if (error && typeof error.message === "string" && error.message) return error.message;
  return "The job failed.";
}

/**
 * The age of a stamp as a card's header words: "just now", "5 min ago", "3 h ago" (to 47 hours), then "2 d ago". `now` is a Date;
 * a stamp that is not a time is "".
 */
export function agoText(stamp, now) {
  const then = Date.parse(typeof stamp === "string" ? stamp : "");
  if (!Number.isFinite(then)) return "";
  const seconds = Math.max(0, Math.floor((now.getTime() - then) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 48 * 3600) return `${Math.floor(seconds / 3600)} h ago`;
  return `${Math.floor(seconds / 86400)} d ago`;
}

/**
 * A tab list: buttons with role "tab", the arrow keys, Home and End move between them (a roving tabindex), the hash carries the
 * tab (the caller's onSelect sets it). tabs: [{id, label, name}]; set(selected, {id: {count, tone}}) draws.
 */
export function createTabs(label, tabs, onSelect) {
  const buttons = new Map();
  const el = h("div", { class: "wb-tabs", role: "tablist", "aria-label": label });
  for (const tab of tabs) {
    const button = h("button", { class: "pui-btn pui-surface pui-link wb-tab", type: "button", role: "tab", id: `wb-tab-${tab.id}`, "aria-controls": "wb-tabpanel" });
    button.addEventListener("click", () => onSelect(tab.id));
    buttons.set(tab.id, button);
    el.append(button);
  }
  el.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const ids = tabs.map((t) => t.id);
    const at = ids.findIndex((id) => buttons.get(id) === document.activeElement);
    let next = at < 0 ? 0 : at;
    if (event.key === "ArrowRight") next = (at + 1) % ids.length;
    else if (event.key === "ArrowLeft") next = (at - 1 + ids.length) % ids.length;
    else if (event.key === "Home") next = 0;
    else next = ids.length - 1;
    event.preventDefault();
    buttons.get(ids[next]).focus();
    onSelect(ids[next]);
  });
  const before = new Map();
  return {
    el, buttons,
    /** selected: a tab id; counts: {id: {count, tone}} where count is a number (0 draws no badge) and tone the badge classes. */
    set(selected, counts = {}, names = {}) {
      for (const tab of tabs) {
        const button = buttons.get(tab.id);
        const on = tab.id === selected;
        button.setAttribute("aria-selected", on ? "true" : "false");
        button.setAttribute("tabindex", on ? "0" : "-1");
        button.classList.toggle("is-selected", on);
        const info = counts[tab.id];
        button.setAttribute("aria-label", names[tab.id] || tab.label);
        const rose = info && before.has(tab.id) && info.count > before.get(tab.id) && before.get(tab.id) >= 0;   // a decision arrived (A3): the badge scales once
        before.set(tab.id, info ? info.count : 0);
        fill(button, h("span", { text: tab.label }), info && info.count > 0 ? h("span", { class: `pui-badge ${info.tone} pui-rounded-full${rose ? " is-pop" : ""}`, text: String(info.count) }) : null);
      }
    },
  };
}
