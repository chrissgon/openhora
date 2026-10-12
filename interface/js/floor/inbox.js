// The Inbox tab: one card per open decision of the agent (read whole with `pendingItem`, never changed by the page itself),
// then the resolved lines (read from each task's decisions of every status, MISSING-7) as collapsed items. A decision the
// person just resolved stays as its resolved line, with the result as text, until the tab is left. This module reads and draws;
// every button's request is sent by the card (cards.js).

import * as api from "../api.js";
import { fill, h } from "../dom.js";
import * as format from "../format.js";
import { icon } from "../frame/icons.js";
import { createCard } from "./cards.js";
import { chip } from "./widgets.js";

/**
 * Create the Inbox. env: {project, links, now(), refresh() (read the screen's data again), api (the client's actions, see cards.js)}.
 * Returns {el, update({decisions, requests, bodies, resolved, selected, loading, emptyText})}; emptyText replaces the empty line's words
 * (the Lobby says so when the plan it keeps in the Conversation is the only decision that waits).
 */
export function createInbox(env) {
  const el = h("div", { class: "wb-inbox" });
  const items = new Map();       // decision id -> the body of pendingItem
  const reading = new Set();     // ids being read now
  const failed = new Map();      // id -> the message of the read that failed
  const cards = new Map();       // id -> the card
  let requestIds = new Set();
  let last = null;
  let focused = null;
  let shown = "";
  let ours = null;               // {link, until}: the "Open" link this module focused
  let wantOpen = null;           // {path, until}: the "Open" link of a document that was just closed, to take the focus when its card is drawn

  const cardEnv = {
    project: env.project, now: env.now, api: env.api, links: env.links,
    get requestIds() { return requestIds; },
    reread: async (id) => {
      const fresh = await api.pendingItem(env.project, id);
      items.set(id, fresh);
      return fresh;
    },
    task: (id) => api.task(env.project, id),      // a review card reads its task for the file-drop line (A-30)
    changed: () => {
      env.refresh();
      draw();
    },
    gone: (id) => {
      cards.delete(id);
      items.delete(id);
      env.refresh();
      draw();
    },
  };

  async function read(id) {
    if (reading.has(id) || items.has(id)) return;
    reading.add(id);
    try {
      items.set(id, await api.pendingItem(env.project, id));
      failed.delete(id);
    } catch (e) {
      failed.set(id, e && e.name === "ApiError" && e.status === 404 ? "That item is not there any more." : (e && e.message) || "The decision could not be read.");
    }
    reading.delete(id);
    draw();
  }

  function cardFor(id) {
    const item = items.get(id);
    if (!item) return null;
    let card = cards.get(id);
    if (!card) {
      card = createCard(item, cardEnv);
      cards.set(id, card);
    } else if (card.item() !== item) {
      card.update(item);
    }
    return card;
  }

  /** What the person answered, commented or noted (A-41): a label and the text as plain text (textContent), never Markdown or markup; none when nothing was saved. */
  function saidBlock(said) {
    if (!said || !said.text) return null;
    return h("div", { class: "wb-res-said" }, h("span", { class: "wb-card-label", text: said.label }), h("p", { text: said.text }));
  }

  const openLines = new Map();     // resolved decision id -> whether the person opened (true) or closed (false) its line; a line the person did not touch is open only when it is the newest

  /**
   * R-38: the resolved decisions as a vertical timeline, newest first. Each item has the outcome's icon (a check, or a cross for a rejection or a cancellation), a line that joins the
   * icons, and is an accordion: its title with the kind and the age under it; opened, the date and what the person said (`saidBlock`).
   */
  function resolvedList(lines) {
    if (!lines.length) return null;
    return h("div", { class: "wb-resolved-tl wb-resolved-list" }, h("span", { class: "wb-sec-head", text: "Resolved" }),
      h("ol", { class: "pui-timeline wb-tl", "aria-label": "Resolved decisions, newest first" }, lines.map((line, index) => {
        const ago = line.age ? ` · ${format.agoPhrase(line.age)}` : "";
        const details = h("details", { class: "wb-tl-acc wb-resolved-item", open: openLines.has(line.id) ? openLines.get(line.id) : index === 0 },
          h("summary", {}, h("span", { class: "wb-tl-text" }, h("strong", { class: "wb-tl-title wb-resolved-title", text: line.title }), h("span", { class: "wb-tl-sub wb-muted", text: `${line.text}${ago}` })),
            h("span", { class: "wb-task-mark", "aria-hidden": "true" }, icon("chevron-down", 16))),
          h("div", { class: "wb-tl-body" }, h("p", { class: "wb-muted wb-resolved-body", text: line.when ? `Resolved ${line.when}` : "Resolved" }), saidBlock(line.said)));
        // only a choice that differs from the default is kept: the toggle event the browser fires when a line is made open must not make an older line stay open beside a newer one
        details.addEventListener("toggle", () => {
          if (details.open === (index === 0)) openLines.delete(line.id);
          else openLines.set(line.id, details.open);
        });
        return h("li", { class: "pui-checkpoint wb-tl-item" }, h("span", { class: `pui-checkpoint-icon ${line.tone} wb-tl-icon` }, icon(line.icon || "check", 14)), details);
      })));
  }

  function draw() {
    if (!last) return;
    const open = last.decisions.map((d) => d.id);
    const nodes = [];
    for (const id of open) {
      const card = cardFor(id);
      if (card) nodes.push(card.el);
      else if (failed.has(id)) nodes.push(h("div", { class: "notice pui-soft pui-error", role: "alert", text: failed.get(id) }));
      else nodes.push(h("div", { class: "wb-busy-card wb-muted", "aria-busy": "true", text: "Loading the decision..." }));
    }
    // a decision the person just resolved stays until the tab is left
    const keep = [];
    for (const [id, card] of cards) {
      if (!open.includes(id) && card.isDone()) keep.push(card.el);
    }
    const empty = !nodes.length && !keep.length;
    const resolved = resolvedList(last.resolved || []);
    const key = JSON.stringify([open, keep.length, empty, (last.resolved || []).map((r) => r.id), last.loading, last.emptyText || ""]) + nodes.map((n, i) => (n.tagName === "ARTICLE" ? "a" : n.textContent)).join("|");
    const signature = key + [...cards.keys()].map((id) => (cards.get(id).isDone() ? id : "")).join(",");
    if (signature !== shown) {
      shown = signature;
      // the "Open" link this module focused keeps the focus through the draws that move its card (for a few seconds); any other focus is the person's
      const held = ours && Date.now() < ours.until && document.activeElement === ours.link ? ours.link : null;
      fill(el, empty ? h("p", { class: "wb-empty-line", text: last.loading ? "Loading the floor..." : last.emptyText || "Nothing waits for you on this floor." }) : h("div", { class: "wb-cards" }, keep, nodes), resolved);
      if (held && held.isConnected && document.activeElement !== held && held.focus) held.focus();
    }
    if (last.selected !== null && last.selected !== undefined && focused !== last.selected) {
      const card = cards.get(last.selected);
      if (card) {
        focused = last.selected;
        card.el.scrollIntoView ? card.el.scrollIntoView({ block: "nearest" }) : null;
        card.focusTitle();
      }
    }
    focusOpenLink();
  }

  /** Give the focus to the "Open" link of the document the person just closed, as soon as its card is drawn (a few seconds at most). */
  function focusOpenLink() {
    if (!wantOpen) return;
    if (Date.now() > wantOpen.until) {
      wantOpen = null;
      return;
    }
    // only the cards that are drawn now: after a reset `el` still holds the old nodes until the next draw replaces them
    const label = `Open ${wantOpen.path}`;
    let link = null;
    for (const card of cards.values()) {
      if (!link && card.el.querySelectorAll) link = [...card.el.querySelectorAll("a")].find((a) => a.getAttribute("aria-label") === label) || null;
    }
    if (link) {
      wantOpen = null;
      link.focus();
      ours = { link, until: Date.now() + 5000 };
    }
  }

  return {
    el,
    update(data) {
      last = data;
      requestIds = new Set((data.requests || []).map((r) => r.id));
      for (const d of data.decisions) read(d.id);
      // an id that is no longer open and not just resolved is dropped
      for (const [id, card] of cards) {
        if (!data.decisions.some((d) => d.id === id) && !card.isDone()) {
          cards.delete(id);
          items.delete(id);
        }
      }
      draw();
    },
    /** The document at `path` was closed: the focus goes back to the "Open" link that opened it, when the card is (or gets) drawn. */
    focusOpen(path) {
      wantOpen = { path, until: Date.now() + 5000 };
      focusOpenLink();
    },
    /** True while any card has a request in flight. */
    busy() {
      return [...cards.values()].some((card) => card.isBusy());
    },
    /** Forget what was read (the tab was left): a just-resolved card goes. */
    reset() {
      wantOpen = null;
      ours = null;
      cards.clear();
      items.clear();
      failed.clear();
      focused = null;
      shown = "";
    },
  };
}
