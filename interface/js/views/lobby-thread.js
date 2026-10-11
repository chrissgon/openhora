// The conversation's log: the messages, oldest first (the person's on the right, the planning agent's on the left, each with
// its age), and under the message that produced a request that request's block. It is drawn by keys, not wholesale: a message
// is built once (its age and its word "queued", A-23, are kept current), a block again only when what it shows changed, so a poll that changed nothing touches no element and the focus
// and a typed note stay where they are. The person's message is text, never markup; the agent's reply is drawn by the Markdown
// renderer, which builds nodes and leaves raw HTML as text.

import { h } from "../dom.js";
import { renderMarkdown } from "../markdown.js";
import { replyView } from "../floor/reply.js";
import { createBlock } from "./lobby-request.js";
import { EMPTY_TEXT, QUEUED_WORD, metaOf, nameOf, placeBlocks, signatureOf } from "./lobby-model.js";

/** The log. options: {api, project, signal, onChanged, onCancel, onRoute(request, flow), announce}. Returns {el, update(state), focusDecision(request, decision), focusRequest(request)}. */
export function createThread({ api, project, signal, onChanged, onCancel, onRoute, announce }) {
  const el = h("div", { class: "wb-thread", role: "log", "aria-live": "polite", "aria-label": "Conversation with the planning agent", tabindex: "0" });
  const messages = new Map();     // id -> {el, meta, message}
  const blocks = new Map();       // request id -> {el, sig, block}
  const expanded = new Set();     // request ids whose whole text is open: a block rebuilt by a poll is given it back
  const chosen = new Map();       // request id -> the flow chosen beside "Route it" (E-20): a block rebuilt by a poll is given it back
  const empty = h("p", { class: "wb-empty", text: "" });
  let stick = true;               // the thread follows its end until the person scrolls away from it; scrolling back to within 48 px of the end follows again
  el.addEventListener("scroll", () => { stick = el.scrollHeight - el.scrollTop - el.clientHeight < 48; });

  /** The meta line over a message: its words, and the word "queued" (A-23) in its own span so that it alone takes the warn ink. */
  function drawMeta(meta, message, now) {
    const line = metaOf(message, now);
    const tail = ` · ${QUEUED_WORD}`;
    if (message.queued && line.endsWith(tail)) meta.replaceChildren(line.slice(0, -tail.length), " · ", h("span", { class: "wb-queued", text: QUEUED_WORD }));
    else meta.replaceChildren(line);
  }

  function messageNode(message, now) {
    const meta = h("time", { class: "wb-msg-meta wb-muted", datetime: message.created_at || false, title: message.created_at || false });
    drawMeta(meta, message, now);
    const mine = message.role === "user";     // what the person typed is shown as typed; the agent's reply is drawn as Markdown
    // the agent's reply opens in place when it is long (A-67, M-25); the bubble is kept by the thread, so the choice lives with it
    const bubble = mine ? h("div", { class: "wb-bubble pui-soft pui-theme", text: message.text }) : h("div", { class: "wb-bubble wb-bubble-agent" }, replyView(renderMarkdown(message.text)).el);
    const node = h("div", { class: `wb-msg ${message.role === "user" ? "is-user" : "is-agent"}${message.queued ? " is-queued" : ""}`, role: "article", "aria-label": nameOf(message, now) }, meta, bubble);
    return { el: node, meta, message };
  }

  return {
    el,
    /**
     * state: {messages, requests (status.requests), pending (status.pending), bodies ({[requestId]: task answer}), now,
     * loading, routing (a Set of request ids being routed), notices (a Map of request id -> {title, text}, a route that failed), flows (the
     * project's flows, or null while unread), remembered (a Map of request id -> the flow chosen in the form this session)}.
     */
    update({ messages: list, requests, pending, bodies, now, loading, routing, notices, flows = null, remembered = null }) {
      // a request's title that has the focus (the route of a request line puts it there) keeps it when a draw builds that block again
      const active = document.activeElement;
      const titled = [];
      for (const [id, held] of blocks) {
        if (active && active.classList && active.classList.contains("wb-lobby-request-title") && held.el.contains(active)) titled.push(id);
      }
      const placed = placeBlocks(list, requests);
      const desired = [];
      const byId = new Map((requests || []).map((r) => [r.id, r]));

      function blockFor(requestId, viaMessage) {
        const request = byId.get(requestId);
        if (!request) return null;
        const body = bodies[requestId] || null;
        const bodySig = body ? (body.pending || []).map((p) => `${p.id}:${p.status}:${p.resolution || ""}`).join(",") : "-";
        const open = (pending || []).filter((p) => p.task_id === requestId).length;
        const routeNotice = (notices && notices.get(requestId)) || null;
        const runBusy = (requests || []).some((r) => (r.routing && r.id !== requestId) || (r.tasks || []).some((t) => t.state === "running"));      // a run holds the project: Route it is queued, and says so
        const routingNow = Boolean(routing && routing.has(requestId)) || Boolean(request.routing);      // A-51: this page's click, or a run the service reports
        const kept = (remembered && remembered.get(requestId)) || "";
        const sig = `${signatureOf(request, pending)}|${bodySig}|${routingNow ? "r" : ""}${runBusy ? "b" : ""}|${viaMessage ? "m" : "t"}|${request.title}|${routeNotice ? `${routeNotice.title}:${routeNotice.text}` : ""}|${flows ? flows.length : "-"}|${kept}`;
        const held = blocks.get(requestId);
        if (held && held.sig === sig) return held.el;
        const block = createBlock({ api, project, request, body, open, now, signal, onChanged, onCancel, onRoute, announce, routing: routingNow, runBusy, viaMessage, routeNotice,
          expanded: expanded.has(requestId), onExpand: (open) => { if (open) expanded.add(requestId); else expanded.delete(requestId); },
          flows, flow: chosen.get(requestId) || "", onFlow: (value) => chosen.set(requestId, value), remembered: kept });
        blocks.set(requestId, { el: block.el, sig, block });
        return block.el;
      }

      for (const message of list) {
        let held = messages.get(message.id);
        if (!held) {
          held = messageNode(message, now);
          messages.set(message.id, held);
        } else {
          drawMeta(held.meta, message, now);
          held.el.setAttribute("aria-label", nameOf(message, now));
          held.el.classList.toggle("is-queued", Boolean(message.queued));      // the word "queued" goes when the reply arrives
        }
        desired.push(held.el);
        const request = placed.byMessage.get(message.id);
        if (request !== undefined) {
          const node = blockFor(request, true);
          if (node) desired.push(node);
        }
      }
      for (const request of placed.trailing) {
        const node = blockFor(request, false);
        if (node) desired.push(node);
      }
      for (const [id, held] of blocks) {
        if (!desired.includes(held.el)) blocks.delete(id);
      }
      empty.textContent = loading ? "Loading the conversation..." : EMPTY_TEXT;
      if (!list.length && !desired.length) desired.push(empty);
      desired.forEach((node, i) => {
        if (el.children[i] !== node) el.insertBefore(node, el.children[i] || null);
      });
      while (el.children.length > desired.length) el.lastElementChild.remove();
      for (const id of titled) {
        const held = blocks.get(id);
        if (held && held.el.isConnected && !held.el.contains(document.activeElement)) held.block.focusTitle();
      }
      if (stick) el.scrollTop = el.scrollHeight;       // the thread opens at its end and follows it (b-5) until the person scrolls away from the end
    },
    /**
     * Scroll to the block of a request and focus its title (the route `.../conversation/request/<n>`). Returns false when the block is not drawn
     * (the request is not there, or not read yet): the caller asks again after the next draw.
     */
    focusRequest(requestId) {
      const held = blocks.get(requestId);
      if (!held || !held.el.isConnected) return false;
      held.el.scrollIntoView({ block: "start" });
      held.block.focusTitle();
      return true;
    },
    /** Move the focus to the title of a decision's card, when it is drawn. */
    focusDecision(requestId, decisionId) {
      const held = blocks.get(requestId);
      if (held) held.block.focusCard(decisionId);
    },
  };
}
