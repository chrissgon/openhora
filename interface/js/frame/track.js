// F-6 the tracking bar and its "Now on" card. Desktop and phone have their own markup (the phone's is a row that opens
// a list of the steps in a sheet); CSS shows one of them.

import { h } from "../dom.js";
import { keepFocus } from "./arrows.js";
import { icon } from "./icons.js";

// Node states (the design system's state table): the class of the icon and its glyph. `failed` and `blocked` use the x,
// `cancelled` the minus (OPEN-14, only icons the design tool's bundle holds).
const NODE = {
  done: ["pui-success pui-soft", "check"], waiting: ["pui-warn pui-soft", "circle-alert"], running: ["pui-theme pui-outline is-running", "activity"],
  ready: ["pui-muted pui-outline", "clock"], requested: ["pui-muted pui-outline", "clock"], planned: ["pui-muted pui-outline", "clock"],
  failed: ["pui-error pui-soft", "x"], blocked: ["pui-error pui-outline", "x"], cancelled: ["pui-muted pui-outline", "minus"],
};

function nodeIcon(state, size) {
  const [cls, glyph] = NODE[state] || NODE.ready;
  return h("span", { class: `pui-checkpoint-icon ${cls}`, "aria-hidden": "true" }, icon(glyph, size));
}

function badge(request) {
  return h("span", { class: "pui-badge pui-muted pui-soft pui-rounded-full wb-req-id", text: `#${request.id}` });
}

// The request selector (WP-9.8): the request's number as a chip. With more than one open request the chip opens a small list of them
// (number, title, state), and a previous and a next button sit beside it; with one it stays a plain badge. Keyboard: the chip opens
// the list, Up and Down move through it, Enter chooses, Escape closes and the focus returns to the chip.
function selector(model, onSelect) {
  const r = model.request;
  // F1-D12: the list is oldest first (#7 then #9), as the prototype draws it; Previous goes to the older request and Next to the newer one
  const requests = [...(model.requests || [])].sort((a, b) => a.id - b.id);
  if (requests.length < 2) return badge(r);
  const at = requests.findIndex((q) => q.selected);
  const move = (delta) => onSelect(r.projectId, requests[(at + delta + requests.length) % requests.length].id);
  const prev = h("button", { class: "pui-btn pui-surface pui-outline wb-req-step", type: "button", "aria-label": "Previous request" }, icon("chevron-left", 14));
  const next = h("button", { class: "pui-btn pui-surface pui-outline wb-req-step", type: "button", "aria-label": "Next request" }, icon("chevron-right", 14));
  prev.addEventListener("click", () => move(-1));
  next.addEventListener("click", () => move(1));
  const chip = h("button", {
    class: "pui-btn pui-surface pui-outline wb-req-chip", type: "button", "aria-haspopup": "listbox", "aria-expanded": "false",
    "aria-label": `Request ${r.id}, ${requests.length} open. Choose a request`,
  }, h("span", { text: `#${r.id}` }), icon("chevron-down", 12));
  const options = requests.map((q) => h("li", { role: "none" },
    h("button", {
      class: `wb-req-option${q.selected ? " is-selected" : ""}`, type: "button", role: "option", "aria-selected": q.selected ? "true" : "false", "data-request": String(q.id),
      "aria-label": `Request ${q.id}, ${q.title}, ${q.running ? "running" : q.state}`, title: q.title,   // a long title is cut with an ellipsis: the whole of it is the tooltip
    }, h("span", { class: "pui-badge pui-muted pui-soft pui-rounded-full", text: `#${q.id}` }), h("span", { class: "wb-req-option-title", text: q.title, title: q.title }),
    h("span", { class: "wb-req-option-state", text: q.running ? "running" : q.state }))));
  const list = h("ul", { class: "wb-req-menu", role: "listbox", "aria-label": "Open requests", hidden: true }, options);
  const close = (refocus) => {
    list.hidden = true;
    chip.setAttribute("aria-expanded", "false");
    if (refocus) chip.focus();
  };
  const open = (focusRequest = null) => {
    const box = chip.getBoundingClientRect();
    list.style.setProperty("--wb-x", `${box.left.toFixed(1)}px`);
    list.style.setProperty("--wb-y", `${(box.top - 6).toFixed(1)}px`);
    list.hidden = false;
    chip.setAttribute("aria-expanded", "true");
    const target = focusRequest !== null ? list.querySelector(`[data-request="${focusRequest}"]`) : null;
    (target || list.querySelector(".is-selected") || list.querySelector("button")).focus();
  };
  chip.addEventListener("click", () => (list.hidden ? open() : close(true)));
  list.addEventListener("mousedown", (event) => event.preventDefault());   // Safari does not focus a clicked button: keep the focus where it is so the list stays open for the click
  for (const button of list.querySelectorAll("button")) {
    button.addEventListener("click", () => {
      close(true);
      onSelect(r.projectId, Number(button.getAttribute("data-request")));
    });
  }
  list.addEventListener("keydown", (event) => {
    const buttons = [...list.querySelectorAll("button")];
    const here = buttons.indexOf(document.activeElement);
    const go = (index) => {
      const button = buttons[index];
      button.focus();
      if (button.scrollIntoView) button.scrollIntoView({ block: "nearest" });   // the list is bounded and scrolls: the row the arrow reached is in view
    };
    if (event.key === "ArrowDown") go(Math.min(buttons.length - 1, here + 1));
    else if (event.key === "ArrowUp") go(Math.max(0, here - 1));
    else if (event.key === "Escape") close(true);
    else return;
    event.preventDefault();
    event.stopPropagation();
  });
  const wrap = h("span", { class: "wb-req-select" }, prev, chip, next, list);
  wrap.addEventListener("focusout", (event) => {
    if (!list.hidden && !(event.relatedTarget && wrap.contains(event.relatedTarget))) close(false);   // focus left: the list closes
  });
  // A poll that changes the bar draws it again: the open list and the focused row (or the chip) are put back by the caller.
  wrap.wbState = () => {
    const active = document.activeElement;
    const option = active && list.contains(active) && active.getAttribute ? active.getAttribute("data-request") : null;
    return { open: !list.hidden, option, chip: active === chip };
  };
  wrap.wbRestore = (state) => {
    if (state.open) open(state.option);
    else if (state.chip) chip.focus({ preventScroll: true });
  };
  return wrap;
}

export function createTrack({ onOpenSteps, onSelectRequest = () => {} }) {
  const desktop = h("div", { class: "wb-track-desktop" });
  const phone = h("div", { class: "wb-track-phone" });
  const el = h("section", { class: "pui-card wb-track", role: "region", "aria-label": "Tracking bar" }, desktop, phone);

  function stepsList(model, size, vertical = false) {
    return h("ol", { class: `pui-timeline${vertical ? "" : " pui-group-row"} wb-steps`, "aria-label": `Request ${model.request.id}, ${model.request.title}, ${model.doneCount} of ${model.total} steps done` },
      model.steps.map((s) => h("li", { class: "pui-checkpoint wb-step" },
        nodeIcon(s.state, size),
        h("a", { class: "wb-step-text", href: s.link, "aria-label": s.name, title: s.waits ? s.waits.join("; ") : null },
          h("strong", { class: "wb-step-title", text: s.title }), h("span", { class: "wb-step-sub", text: s.sub })))));
  }

  function nowCard(model) {
    if (!model.now) {
      return h("div", { class: "wb-now" },
        h("span", { class: "wb-now-where", text: "Nothing is running" }),
        h("strong", { class: "wb-now-title", text: model.request.title || `Request ${model.request.id}` }),
        h("span", { class: "wb-now-sub", text: `request #${model.request.id} · ${model.request.state}` }));
    }
    const now = model.now;
    return h("div", { class: "wb-now" },
      h("span", { class: "wb-now-where", text: now.where }),
      h("a", { class: "wb-now-title", href: now.link, text: now.title }),
      h("div", { class: "wb-now-row" },
        h("span", { class: `pui-chip pui-soft ${now.running ? "pui-theme" : "pui-warn"} wb-chip-small`, text: now.state }),
        h("span", { class: "wb-now-sub", text: now.sub })));
  }

  function draw(model, state) {
    if (state === "loading") {
      desktop.replaceChildren(h("p", { class: "wb-empty wb-track-loading", text: "Loading the request..." }));      // one line in the card, not a column with its own padding (F1-D4)
      phone.replaceChildren(h("p", { class: "wb-empty", text: "Loading the request..." }));
      return;
    }
    if (!model) {   // no open request: the bar is hidden (set() below), nothing is drawn in it
      desktop.replaceChildren();
      phone.replaceChildren();
      return;
    }
    const r = model.request;
    const countText = `${model.doneCount} of ${model.total} steps done`;
    desktop.replaceChildren(
      h("div", { class: "wb-track-left" },
        h("div", { class: "wb-track-head" }, selector(model, onSelectRequest), h("strong", { class: "wb-track-title", text: r.title || `Request ${r.id}` }),
          h("span", { class: "pui-badge pui-muted pui-soft wb-track-project", text: r.project }), h("span", { class: "wb-track-count", text: countText })),
        model.steps.length ? stepsList(model, 13) : h("p", { class: "wb-empty", text: `Request ${r.id} has no steps yet (${r.state}).` })),
      nowCard(model));
    const current = model.now;
    const open = h("button", { class: "pui-btn pui-link wb-track-open", type: "button", "aria-label": `Steps of request ${r.id}, ${countText}. Open the list` },
      h("span", { class: "wb-dots", "aria-hidden": "true" }, model.steps.map((s) => nodeIcon(s.state, 12))),
      h("span", { class: "wb-track-now-text" },
        h("strong", { text: current ? current.title : (r.title || `Request ${r.id}`) }),
        h("span", { class: "wb-step-sub", text: current ? current.where.replace(/^Now on |^Waiting on /, "") : r.state })));      // no state word: the dots carry it (R-8)
    open.addEventListener("click", () => onOpenSteps(`Request ${r.id}, ${r.title || ""}`, model.steps.length ? stepsList(model, 13, true) : h("p", { class: "wb-empty", text: "No steps yet." }), open));
    phone.replaceChildren(
      h("div", { class: "wb-track-head" }, selector(model, onSelectRequest), h("strong", { class: "wb-track-title", text: r.title || `Request ${r.id}` }),
        h("span", { class: "wb-track-count", text: `${model.doneCount} of ${model.total} done` })),
      open);
  }

  let shown = "";
  return {
    el,
    /** model: model.tracking(...) or null; state: "ready", "loading" or "empty"; stale: dim it (the last data after a failed read). */
    set(model, state, stale = false) {
      el.classList.toggle("is-stale", stale);
      el.hidden = !model && state !== "loading";   // the bar hides when the project has no open request
      const key = JSON.stringify([model, state]);
      if (key === shown) return;
      shown = key;
      const before = [...el.querySelectorAll(".wb-req-select")].map((w) => w.wbState());
      keepFocus(el, () => draw(model, state));
      [...el.querySelectorAll(".wb-req-select")].forEach((w, i) => { if (before[i]) w.wbRestore(before[i]); });   // the list stays open across a poll
    },
  };
}
