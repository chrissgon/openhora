// The plan card (handoff cards.md, "Plan card"): the approval point of a plan. It shows the exact thing approved ahead of its
// button: the tasks as blocks, what the plan will wait for (A-29: derived waits with a "Go ahead" box each, a required input nothing writes,
// a circle), the limits, the whole plan hash and the plan as text. "Approve this plan" sends exactly {sha256: <the hash displayed>} and, for
// the boxes ticked, {go_ahead: [task keys]} (a job); "Reject" sends the note when one was typed. The card never changes by itself: after an
// action it asks its host to read again (`onChanged`) and the host draws what it got, a resolved line in place of the card. Text
// from the service goes in as text. A plan with no whole hash offers no approval.

import { h } from "../dom.js";
import * as format from "../format.js";
import { markdownView } from "../markdown-view.js";
import { replyView } from "../floor/reply.js";
import { withheldLine } from "../floor/widgets.js";
import { wordOf } from "../permissions.js";
import * as router from "../router.js";
import { WEB_SOURCES_NOTE, failureText, languageLine, limitsLine, planHash, planText, stackedRow, taskRows, webWithSources } from "./plan-rows.js";
import { createWaitsBlock } from "./plan-waits.js";

let counter = 0;

/** Whether the plan text of each decision is open (A-67): kept across a rebuild of the card, never stored. */
const planOpen = new Map();

/**
 * A plan card. options: {api, project, item (a pending decision with payload and actions), now (Date), onChanged(): Promise,
 * signal, announce(text) (optional: a sentence for the live region), can(op, kind) (optional: whether the page may do an operation, js/permissions.js; all allowed
 * when left out), noteText and onNote(value) (optional: the reject note typed so far, given back to a card built again, and told when it changes)}. Returns {el, focus()}. `api` is the client module (`approve`, `reject`, `pollJob`), passed in so a test can stand in for it.
 * A button the policy withholds is not drawn, the go-ahead boxes are left out when `approve` with the kind go-ahead is withheld, and a line under the remaining
 * controls says which operations are turned off; the card is built again (the thread's signature) when what the page may do changes.
 */
export function createPlanCard({ api, project, item, now, onChanged, signal, announce, can = () => true, noteText = "", onNote = null }) {
  counter += 1;
  const titleId = `wb-plan-title-${counter}`;
  const shown = planHash(item);
  const actions = Array.isArray(item.actions) ? item.actions : [];
  const rows = taskRows(item);

  const kind = h("span", { class: "pui-badge pui-warn pui-soft", text: format.kindWord(item.kind) });
  const age = format.age(item.created_at, now);
  const meta = h("span", { class: "wb-card-meta" },
    `#${item.id} · `,
    item.task_id !== null && item.task_id !== undefined ? h("a", { class: "pui-link pui-theme", href: router.lobbyHash(project), text: `request #${item.task_id}` }) : null,
    item.task_id !== null && item.task_id !== undefined ? " · " : null,
    `${format.agentWord(item.agent)}${age ? ` · ${format.agoPhrase(age)}` : ""}`);
  if (item.created_at) meta.setAttribute("title", item.created_at);
  const title = h("h3", { class: "wb-card-title", id: titleId, tabindex: "-1", text: item.title || `Plan ${item.id}` });

  // R-47: the plan's tasks are blocks at every width (the panel is narrower than the seven columns need): the number, the task, its skill and agent, and
  // what it waits for; the table the card had is gone
  const list = h("ol", { class: "wb-plan-list", "aria-label": "Plan tasks" }, rows.map((r) => {
    const s = stackedRow(r);
    const flagged = webWithSources(r);   // D16: a task that uses the web and receives sources is shown as such, before the person approves
    return h("li", { class: flagged ? "wb-plan-task wb-plan-task-web-sources" : "wb-plan-task" },
      h("span", { class: "wb-task-n", text: r.n }),
      h("div", { class: "wb-plan-task-text" },
        h("strong", { class: "wb-cell-task", text: r.task }),
        h("span", { class: "wb-muted wb-cur-sub" }, h("code", { class: "mono wb-cell-skill", text: s.skill }), s.agent ? ` · ${s.agent}` : ""),
        h("span", { class: "wb-muted wb-cur-sub", text: s.tail }),
        flagged ? h("span", { class: "pui-badge pui-warn pui-soft wb-plan-web-sources", title: WEB_SOURCES_NOTE, text: "Web task with sources" }) : null,
        flagged ? h("span", { class: "wb-cur-sub wb-plan-web-sources-note", text: WEB_SOURCES_NOTE }) : null));
  }));

  const waits = createWaitsBlock(item.payload, { can });
  const lacking = [];
  const allow = (op, kind) => {
    if (can(op, kind)) return true;
    const word = wordOf(op, kind);
    if (!lacking.includes(word)) lacking.push(word);
    return false;
  };
  if (waits && waits.withheld) allow("approve", "go-ahead");
  const limits = limitsLine(item);
  const language = languageLine(item);
  const hashBlock = shown
    ? h("div", { class: "wb-plan-hash-block" }, h("span", { class: "wb-card-label", text: "Plan hash" }), h("code", { class: "wb-plan-hash", tabindex: "0", role: "group", "aria-label": "Plan hash", text: shown }))
    : h("p", { class: "wb-card-note", text: "This plan carries no hash, so it cannot be approved from here." });
  const text = planText(item);
  const asText = text
    ? h("details", { class: "wb-disclosure wb-plan-text" }, h("summary", { text: "Plan as text" }), h("div", { class: "wb-plan-body" }, replyView(markdownView(text, { name: "the plan", renderedLabel: "Plan as text", plainClass: "wb-plan-pre" }), { open: Boolean(planOpen.get(item.id)), onToggle: (value) => planOpen.set(item.id, value) }).el))
    : null;

  const noteId = `${titleId}-note`;
  const note = h("input", { class: "pui-input wb-lobby-field wb-field-input", id: noteId, type: "text", autocomplete: "off" });
  note.value = noteText;
  note.addEventListener("input", () => { if (onNote) onNote(note.value); });
  const noteGroup = h("label", { class: "pui-field-group wb-field", for: noteId }, h("span", { text: "Note (optional, used when you reject)" }), note);
  const error = h("div", { class: "notice pui-soft pui-error wb-card-error", role: "alert", hidden: true });
  const working = h("span", { class: "wb-lobby-working", hidden: true, text: "Working..." });
  const approve = actions.includes("approved") && shown && allow("approve", "plan")
    ? h("button", { class: "pui-btn pui-solid pui-theme wb-card-button", type: "button", text: "Approve this plan" }) : null;
  const reject = actions.includes("rejected") && allow("reject")
    ? h("button", { class: `pui-btn ${approve ? "pui-surface pui-outline" : "pui-solid pui-theme"} wb-card-button`, type: "button", text: "Reject" }) : null;
  const buttons = [approve, reject].filter(Boolean);
  const row = buttons.length ? h("div", { class: "wb-card-buttons wb-card-actions" }, ...buttons, working) : null;

  const el = h("article", { class: "pui-card wb-card wb-plan-card", "aria-labelledby": titleId },
    h("div", { class: "wb-card-head" }, kind, meta),
    h("div", { class: "pui-card-content wb-card-content" },
      title, list, language ? h("p", { class: "wb-card-note wb-plan-language", text: language }) : null, waits ? waits.el : null, limits ? h("p", { class: "wb-card-note", text: limits }) : null, hashBlock, asText,
      reject ? noteGroup : null, error, row, withheldLine(lacking)));

  let sending = false;

  function showError(message) {
    error.textContent = message;
    error.hidden = !message;
  }

  function lock(on, active, word) {
    sending = on;
    for (const button of buttons) {
      button.disabled = on;
      button.removeAttribute("aria-busy");
    }
    note.disabled = on;
    if (waits) waits.setDisabled(on);
    working.hidden = !(on && active === approve);
    if (on) {
      active.setAttribute("aria-busy", "true");
      active.dataset.word = active.textContent;
      active.textContent = word;
    } else if (active && active.dataset.word) {
      active.textContent = active.dataset.word;
    }
  }

  async function run(active, word, call, isJob) {
    if (sending) return;
    showError("");
    lock(true, active, word);
    try {
      const first = await call();
      if (isJob) {
        const done = await api.pollJob(first.job, 1000, { signal });
        if (done.state === "failed") {
          const failure = done.error || {};
          throw Object.assign(new Error(failure.message || "The job failed."), { status: failure.status || 500, word: failure.error || "internal" });
        }
      }
    } catch (e) {
      if (e && e.name === "AbortError") return;
      showError(failureText(e));
      lock(false, active);
      await onChanged();    // the card is read again: a decision resolved elsewhere becomes its resolved line
      return;
    }
    if (announce) announce(active === approve ? "Plan approved" : "Plan rejected");
    await onChanged();      // the host draws what it read: the resolved line in place of this card
    if (el.isConnected) lock(false, active);
  }

  // the boxes ticked when the button is pressed travel with the hash shown; with none ticked the call is the plain one
  const approveCall = () => {
    const ahead = waits ? waits.keys() : [];
    return ahead.length ? api.approve(project, item.id, shown, { goAhead: ahead }) : api.approve(project, item.id, shown);
  };
  if (approve) approve.addEventListener("click", () => run(approve, "Approving...", approveCall, true));
  if (reject) {
    reject.addEventListener("click", () => run(reject, "Rejecting...", () => api.reject(project, item.id, note.value.trim() ? note.value : undefined), false));
  }

  return {
    el,
    focus() {
      title.focus({ preventScroll: false });
    },
  };
}
