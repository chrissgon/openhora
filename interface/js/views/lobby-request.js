// A request's block in the Lobby's conversation: the request line (its id, title and state, "Cancel request", and "Route it" when
// the request waits for a route nobody is asking for), then the request's decisions: an open plan under the message that produced it as
// the plan card, any other open decision as a line that points at the Inbox (its card is the Floor's pattern), a decision no longer open as a resolved line. And the
// dialog that asks before a request is cancelled. Text from the service goes in as text.

import { createPlanCard } from "../cards/plan.js";
import { failureText } from "../cards/plan-rows.js";
import { h } from "../dom.js";
import { withheldLine } from "../floor/widgets.js";
import * as format from "../format.js";
import { routingWords } from "../model.js";
import * as router from "../router.js";
import { QUEUE_REASON, ago, flowOptions, requestLine, requestWords, resolvedWord } from "./lobby-model.js";

/** The line of a decision that is no longer open: a chip with "<kind> <resolution>" and the title and age. */
function resolvedLine(item, now) {
  const good = item.status === "resolved" && item.resolution !== "rejected";
  const when = ago(item.resolved_at || item.created_at, now);
  return h("div", { class: "wb-lobby-resolved" },
    h("span", { class: `pui-chip pui-soft ${good ? "pui-success" : "pui-muted"} wb-chip-small`, text: resolvedWord(item) }),
    h("span", { class: "wb-lobby-resolved-text", text: `${item.title || ""}${when ? ` · ${when}` : ""}` }));
}

/**
 * A line that points at the place where a decision's card is: its kind, title and age, then `link` (an anchor the caller builds with
 * the router). The Conversation uses it for a card that lives in the Inbox and the Inbox for a plan card that lives in the
 * Conversation, so a card is drawn in one place only.
 */
export function pointerLine(item, now, link) {
  const when = ago(item.created_at, now);
  return h("div", { class: "wb-lobby-resolved wb-pointer" },
    h("span", { class: "pui-badge pui-warn pui-soft", text: format.kindWord(item.kind) }),
    h("span", { class: "wb-lobby-resolved-text" }, h("strong", { class: "wb-pointer-title", text: item.title || "" }), when ? ` · ${when}` : ""),
    link);
}

/** An open decision whose card is in the Inbox: a line that points at it. */
function pointer(project, item, now) {
  return pointerLine(item, now, h("a", { class: "pui-link pui-theme", href: router.lobbyHash(project, "inbox", item.id), text: "Open in the Inbox",
    "aria-label": `Open ${format.kindWord(item.kind)} ${item.id} in the Inbox` }));
}

/**
 * One request's block. options: {api, project, request (a row of status.requests), body (the `task` answer, or null while it is
 * read), open (open decisions on it in status), now, signal, onChanged(), onCancel(request), onRoute(request, flow), announce(text),
 * viaMessage (a message of the planning agent names the request; false for a request made from the form, OPEN-24), routeNotice
 * ({title, text} of a route that failed, or null: it sits under the request's line), expanded (the request's whole text is open) and
 * onExpand(open) (told when the person opens or closes it, so a rebuilt block can be given the state back), flows (the project's flows,
 * read once, or null: with them a request that waits for its route has a flow select beside "Route it", E-20), flow (the choice to give the
 * select back to a rebuilt block), onFlow(value) (told when the person chooses) and remembered (the flow chosen in the form this session,
 * kept in memory: then there is no select and "Route it" sends that flow), can(op, kind) (whether the page may do an operation, js/permissions.js, all allowed when
 * left out: "Route it" is `route`, and when it is withheld a line under the request's actions says so; "Cancel request" is a brake and is never withheld)}.
 * The plan card is drawn here only when a message names the request; otherwise its card is in the Inbox and this is a line that points at it.
 * The block has an id (`wb-request-<n>`) that the route `#/p/<id>/lobby/conversation/request/<n>` scrolls to. Returns {el, focusCard(id), focusTitle()}.
 */
export function createBlock({ api, project, request, body, open, now, signal, onChanged, onCancel, onRoute, routing, runBusy = false, announce, viaMessage = true, routeNotice = null, expanded = false, onExpand = null,
  flows = null, flow = "", onFlow = null, remembered = "", can = () => true, notes = null }) {
  const line = requestLine(request, open);
  const words = requestWords(request, body);
  const number = `Request #${request.id}`;
  const named = words.title ? `${number}: ${words.title}` : number;
  const fullId = `wb-request-full-${request.id}`;
  // one line: the badge says the number, so the visible text is the title alone (the number alone when there is none); its tooltip holds the
  // whole text, its accessible name keeps the number, and a click opens the whole text under the line
  const titleButton = h("button", { class: "pui-btn pui-link wb-lobby-request-title", type: "button", title: `${number}: ${words.full || words.title}`.replace(/: $/, ""),
    "aria-label": named, "aria-expanded": expanded ? "true" : "false", "aria-controls": fullId, text: words.title || number });
  const fullText = h("p", { class: "wb-lobby-request-full", id: fullId, hidden: !expanded, text: words.full || words.title || number });
  titleButton.addEventListener("click", () => {
    fullText.hidden = !fullText.hidden;
    titleButton.setAttribute("aria-expanded", fullText.hidden ? "false" : "true");
    if (onExpand) onExpand(!fullText.hidden);
  });
  const notice = routeNotice
    ? h("div", { class: `wb-lobby-notice-card notice${routeNotice.tone === "info" ? "" : " pui-soft pui-error"} wb-lr-note`, role: routeNotice.tone === "info" ? "status" : "alert" },
      h("strong", { class: "wb-lobby-notice-title", text: routeNotice.title }), h("span", { text: routeNotice.text })) : null;
  // A-51: while the router works on the request (the page's own click, or a run the service reports in `routing`) the line says `Routing...`: no `Route it`, no flow
  // select, and no `Cancel request`, because the store refuses to cancel a request a run holds
  const cancel = line.cancellable && !routing
    ? h("button", { class: "pui-btn pui-link pui-error wb-lobby-cancel-link", type: "button", text: "Cancel request", "aria-label": `Cancel request ${request.id}` }) : null;
  const routeAllowed = can("route");
  const route = line.routable && routeAllowed
    ? h("button", { class: "pui-btn pui-surface pui-outline wb-small-button wb-route-button", type: "button", text: routing ? "Routing..." : "Route it", disabled: Boolean(routing),
      "aria-label": routing ? `Request ${request.id} is being routed` : `Route request ${request.id}`, title: request.routing ? routingWords(request, now) : runBusy && !remembered ? QUEUE_REASON : null }) : null;
  // the run's words on an element that wraps, not only on the button's tooltip (a touch screen has no tooltip)
  const runNote = request.routing ? h("span", { class: "wb-lr-run", text: routingWords(request, now) }) : null;
  // After a reload the flow chosen in the form is forgotten: the line offers the flows beside "Route it" (E-20). The page never changes the request's text.
  const options = flows ? flowOptions(flows) : [];
  const chooser = route && !routing && !remembered && options.length > 1
    ? h("select", { class: "pui-input wb-select wb-route-flow", "aria-label": `Flow for request ${request.id}` }, options.map((o) => h("option", { value: o.value, text: o.label })))
    : null;
  if (chooser) {
    chooser.value = flow || "";
    chooser.addEventListener("change", () => { if (onFlow) onFlow(chooser.value); });
  }
  // R-47: the request line is a small bordered block: the number, the title and the state chip in the state's colour on one line; `Route it` and `Cancel request`
  // on the line under it (E-28); the whole text and a notice under those
  const row = h("div", { class: "wb-lobby-request-line", role: "group", "aria-label": line.name },
    h("span", { class: "pui-badge pui-muted pui-soft pui-rounded-full", text: `#${request.id}` }),
    titleButton,
    line.state ? h("span", { class: `pui-chip ${line.tone} wb-chip-small`, text: line.state }) : null);
  const lacking = line.routable && !routeAllowed ? ["route"] : [];
  const actions = chooser || route || cancel ? h("div", { class: `wb-lr-actions${chooser ? " has-flow" : ""}` }, chooser, route, cancel, runNote) : null;
  if (cancel) cancel.addEventListener("click", () => onCancel(request, cancel));
  if (route && !routing) route.addEventListener("click", () => onRoute(request, remembered || (chooser ? chooser.value : "")));

  const cards = new Map();
  const decisions = [];
  const items = body && Array.isArray(body.pending) ? body.pending : [];
  for (const item of items) {
    if (item.status === "open") {
      if (item.kind === "plan" && viaMessage) {
        const card = createPlanCard({ api, project, item, now, onChanged, signal, announce, can,
          noteText: notes ? notes.get(item.id) || "" : "", onNote: notes ? (value) => notes.set(item.id, value) : null });
        cards.set(item.id, card);
        decisions.push(card.el);
      } else {
        decisions.push(pointer(project, item, now));
      }
    } else {
      decisions.push(resolvedLine(item, now));
    }
  }
  const box = line.final ? null : h("div", { class: "wb-request-box" }, row, actions, withheldLine(lacking), fullText, notice);
  const el = h("div", { class: "wb-request-block", id: `wb-request-${request.id}`, tabindex: "-1" }, box, ...decisions);
  return {
    el,
    /** Move the focus to the request's title (the block itself when the request is final and has no line). */
    focusTitle() {
      (line.final ? el : titleButton).focus();
    },
    focusCard(id) {
      const card = cards.get(id);
      if (card) card.focus();
    },
  };
}

/** The dialog "Cancel this request and what is still open under it?". Returns {el, open(request, countText, opener)}. */
export function createCancelDialog({ api, project, onChanged }) {
  const titleId = "wb-cancel-title";
  const heading = h("strong", { class: "wb-card-title", id: titleId, text: "Cancel this request and what is still open under it?" });
  const sub = h("span", { class: "wb-card-note", text: "" });
  const error = h("div", { class: "notice pui-soft pui-error wb-card-error", role: "alert", hidden: true });
  const keep = h("button", { class: "pui-btn pui-surface pui-outline", type: "button", text: "Keep it" });
  const confirm = h("button", { class: "pui-btn pui-error pui-outline", type: "button", text: "Cancel request" });
  const card = h("div", { class: "pui-card wb-dialog-card" },
    h("div", { class: "pui-card-content wb-dialog-content" }, heading, sub, error, h("div", { class: "wb-dialog-buttons" }, keep, confirm)));
  const el = h("dialog", { class: "pui-modal wb-dialog", "aria-labelledby": titleId }, card);
  let current = null;
  let busy = false;

  function setError(text) {
    error.textContent = text;
    error.hidden = !text;
  }
  keep.addEventListener("click", () => {
    if (!busy) el.close();
  });
  el.addEventListener("cancel", (event) => {
    if (busy) event.preventDefault();      // Escape keeps the request; while a cancel is in flight the dialog stays
  });
  confirm.addEventListener("click", async () => {
    if (busy || !current) return;
    busy = true;
    setError("");
    keep.disabled = true;
    confirm.disabled = true;
    confirm.setAttribute("aria-busy", "true");
    confirm.textContent = "Cancelling...";
    try {
      await api.cancel(project, current.id);
      busy = false;
      el.close();
      await onChanged();
    } catch (e) {
      busy = false;
      setError(failureText(e));
    }
    keep.disabled = false;
    confirm.disabled = false;
    confirm.removeAttribute("aria-busy");
    confirm.textContent = "Cancel request";
  });

  return {
    el,
    open(request, countText) {
      current = request;
      sub.textContent = `Request #${request.id}: ${request.title || ""} · ${countText}`;
      setError("");
      if (!el.open) el.showModal();
      keep.focus();
    },
  };
}
