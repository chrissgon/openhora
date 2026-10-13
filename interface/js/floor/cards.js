// The decision cards of the Inbox (handoff cards.md and floor.md): effect, acceptance, question, review and plan, the request
// line and the cancel dialog. A card shows what the service returned for one decision, draws one button per word of its
// `actions` (and none for a word it does not know), and sends exactly what the person typed or clicked: the page decides
// nothing. An effect or a plan is approved only with the hash the card shows, read back from the page's own text at the moment
// of the click. Text from a model, a path or a reason is put in with textContent (through h()), never as markup; the bodies of a
// question, an acceptance, a review and a plan are drawn by the page's own Markdown renderer (markdown.js), which builds nodes and
// leaves raw HTML as text. The exact content of an effect is never rendered: it is what will be sent.
//
// The card is a small state machine over one decision: open, in flight (the control that sent the request reads its "-ing"
// word, every button is disabled, "Working..." shows for a job), failed (the message above the buttons, the typed text
// stays, the card is read again) and done (a resolved line, with the result of an approved effect as text). It is built with
// an environment so a test can run it with a fake document and a fake client:
//   env = {project, now(), api: {answer, release, approve, reject, verdict, cancel, route, flows, handOver, pollJob}, requestIds: Set of request ids,
//          links: {floor(agent), lobby(), open(item, path)}, reread(id) -> item, task(id) -> the task's body (optional: the review card reads
//          the file-drop line from it), changed(id, outcome), gone(id), can(op, kind) (optional: whether the page may do an operation, read at every draw;
//          js/permissions.js; without it everything is allowed)}.
// A control the page may not use (the channel policy of the project) is not drawn, a line under the remaining controls says which operations are turned
// off, and the same check stands in press(): a key that sends without a button (Ctrl+Enter in an answer) is refused there too. Cancelling a request is a brake and
// is never withheld. The service still refuses what it must (409): this only stops the card drawing a control that would be refused.

import { fill, h } from "../dom.js";
import * as format from "../format.js";
import * as router from "../router.js";
import { ENDING, openable } from "../floor-model.js";
import { renderMarkdown } from "../markdown.js";
import { markdownView, onPlainChoice, plainChoice, setPlainChoice } from "../markdown-view.js";
import { replyView } from "./reply.js";
import { createWaitsBlock } from "../cards/plan-waits.js";
import { commandBlock } from "../frame/command.js";
import { fileRefusal, handChooser, handOverStep, toBase64 } from "./hand-file.js";
import { MEDIA_LABEL, isMediaFile, mediaHintText, pickRefusal, progressBar, storedLine, uploadRecording } from "./media-upload.js";
import { reader, wordOf } from "../permissions.js";
import { agoText, chip, errorText, field, isGone, jobText, notice, ring, withheldLine } from "./widgets.js";

// The buttons of each kind, in the drawn order, by the word of `actions` they send, with their "-ing" word.
export const BUTTONS = Object.freeze({
  question: [["answered", "Send answer", "Sending..."]],
  acceptance: [["accepted", "Accept", "Accepting..."], ["rejected", "Reject", "Rejecting..."]],
  review: [["released", "Release (stays a draft)", "Releasing..."], ["answered", "Send back with a comment", "Sending..."]],
  plan: [["approved", "Approve this plan", "Approving..."], ["rejected", "Reject", "Rejecting..."]],
  effect: [["approved", "Approve this exact content", "Approving..."], ["rejected", "Reject", "Rejecting..."]],
});

const RESOLVED = { approved: "approved", accepted: "accepted", rejected: "rejected", answered: "answered", released: "released" };
// The unrecognised route (A-25): the question whose payload names these two actions. The page draws one button for each.
const DONE_TEXT = { route: "Request routed", "cancel-request": "Request cancelled" };

/** Whether a decision is the question of a reply that named no route: a question whose payload `actions` are the two words of the runtime. */
export function isUnrecognised(item) {
  const words = item && item.kind === "question" && item.payload && Array.isArray(item.payload.actions) ? item.payload.actions : [];
  return words.includes("choose-flow") && words.includes("cancel");
}
const NOTE_LABEL = "Note (optional, used when you reject)";

/** The buttons a card draws: for each word of the kind's list that is in `actions`, in order. An unknown word is not drawn. */
export function buttonsFor(item) {
  const words = Array.isArray(item.actions) ? item.actions : [];
  return (BUTTONS[item.kind] || []).filter(([word]) => words.includes(word));
}

/** The limits line of a plan, in the words of plan.build: the first clause only when the plan states how many tasks run at a time (`max_running`). */
export function limitsLine(payload) {
  const limits = (payload && payload.limits) || {};
  const runs = payload && payload.estimate ? payload.estimate.runs_at_least : undefined;
  const parts = [];
  if (Number.isInteger(limits.max_running) && limits.max_running > 0) parts.push(`Up to ${limits.max_running} task${limits.max_running === 1 ? "" : "s"} at a time;`);
  parts.push(`${parts.length ? "each" : "Each"} run at most ${limits.timeout_seconds} s, retried at most ${limits.retries} times.`);
  if (runs !== undefined) parts.push(`At least ${runs} runs.`);
  return parts.join(" ");
}

/** The rows of a plan's table from `payload.tasks`: positions from 1, `depends_on` keys turned into positions. */
export function planRows(payload) {
  const tasks = (payload && Array.isArray(payload.tasks)) ? payload.tasks : [];
  const place = new Map(tasks.map((t, i) => [t.key, i + 1]));
  return tasks.map((t, i) => ({
    n: String(i + 1), title: t.title || "", skill: t.skill || "", agent: t.agent || "-",
    after: (Array.isArray(t.depends_on) && t.depends_on.length) ? t.depends_on.map((k) => place.get(k)).filter((n) => n !== undefined).join(", ") || "-" : "-",
    milestone: t.mandatory_milestone ? "yes (mandatory)" : t.milestone ? "yes" : "no", web: t.web ? "yes" : "no",
  }));
}

const PLAN_COLUMNS = [["n", "#"], ["title", "Task"], ["skill", "Skill"], ["agent", "Agent"], ["after", "After"], ["milestone", "Milestone"], ["web", "Web"]];

/** The count line of the cancel dialog, built from the request's tasks (display words, never a guess). */
export function cancelCount(tasks) {
  const list = Array.isArray(tasks) ? tasks : [];
  if (!list.length) return "No task has been created yet.";
  const started = list.filter((t) => !["planned", "ready", "requested"].includes(t.state)).length;
  return `${list.length} task${list.length === 1 ? "" : "s"}, ${started ? `${started} started` : "none started"}`;
}

let counter = 0;

/**
 * A decision card. `item` is the body of `pendingItem` (id, kind, title, body, payload, payload_sha256, status, actions, agent,
 * task_id, created_at, run_id). Returns {el, id, update(item), focusTitle(), isDone(), outcome()}.
 */
export function createCard(item, env) {
  counter += 1;
  const uid = `wb-card-${counter}`;
  const titleId = `${uid}-title`;
  const root = h("article", { class: "pui-card wb-card", "aria-labelledby": titleId });
  const state = {
    item, busy: null, error: null, done: null, verdict: null, empty: null, typed: { answer: "", comment: "", note: "" },
    route: { open: false, flows: null, flow: "" },     // "Choose a flow": the list read once, and the flow chosen
    drop: null,                                         // {web, takes, line} of the review's task (the file drop), read once
    picked: null,                                       // the file chosen for the hand-over, held until its button sends it (C-17)
    handed: null,                                       // the last file handed over from the review card: {text, error}
    replyOpen: {},                                      // which of the card's replies are open (A-67): per card, never stored
    goAhead: new Set(),                                 // the plan's task keys ticked "Go ahead"
  };
  let inputs = {};
  const can = reader(env);
  let lacking = [];            // the words of the operations withheld in the last draw: the line under the controls

  const api = () => env.api;

  /** The operation a button's word asks the policy about (cancel-request is a brake: none). */
  function askOf(word) {
    const kind = state.item.kind;
    if (word === "answered") return ["answer"];
    if (word === "released") return ["release"];
    if (word === "rejected") return ["reject"];
    if (word === "approved" || word === "accepted") return ["approve", kind];
    if (word === "route" || word === "choose-flow") return ["route"];
    return null;
  }

  /** Whether the page may send the button's word (press() asks this too, without drawing anything). */
  function permits(word) {
    const ask = askOf(word);
    return ask === null || can(ask[0], ask[1]);
  }

  /** Draw-time check: false for an operation the policy withholds, and the word goes to the line under the controls. */
  function allow(op, kind) {
    if (can(op, kind)) return true;
    const word = wordOf(op, kind);
    if (!lacking.includes(word)) lacking.push(word);
    return false;
  }

  // --- the shell -------------------------------------------------------------------------------------------------------------

  function taskLink() {
    const it = state.item;
    const request = env.requestIds && env.requestIds.has(it.task_id);
    if (request || it.kind === "plan" || it.kind === "acceptance") return h("a", { class: "pui-link pui-theme", href: env.links.lobby(), text: `request #${it.task_id}` });
    const agent = it.agent;
    return h("a", { class: "pui-link pui-theme", href: agent ? env.links.floor(agent) : env.links.lobby(), text: `task #${it.task_id}` });
  }

  // The kinds whose body is rendered Markdown carry "Plain text" in their head (R-34): the card's own text as it came, and back; the choice is one for the session
  const RENDERS = ["question", "acceptance", "review"];

  function plainButton() {
    const on = plainChoice();
    const button = h("button", { class: "pui-btn pui-surface pui-outline wb-small-button wb-card-plain", type: "button", "data-key": "plain", "aria-pressed": String(on), text: "Plain text" });
    button.addEventListener("click", () => {
      setPlainChoice(!plainChoice());     // every card that listens draws again (below), this one too
      const next = root.querySelector ? root.querySelector("button.wb-card-plain") : null;
      if (next && next.focus) next.focus();
    });
    return button;
  }

  function header() {
    const it = state.item;
    const request = (env.requestIds && env.requestIds.has(it.task_id)) || it.kind === "plan" || it.kind === "acceptance";
    const where = request ? "Lobby" : (it.agent ? format.agentWord(it.agent) : "");
    const ago = agoText(it.created_at, env.now());
    const meta = h("span", { class: "wb-card-meta" }, `#${it.id} · `, taskLink(), where ? ` · ${where}` : "", ago ? ` · ${ago}` : "");
    if (it.created_at) meta.setAttribute("title", it.created_at);
    // lobby.html draws the route question (the reply that named no route) without `Plain text`: its body is one short sentence
    return h("div", { class: "wb-card-head" }, h("span", { class: "pui-badge pui-warn pui-soft wb-card-kind", text: format.kindWord(it.kind) }), meta, RENDERS.includes(it.kind) && !isUnrecognised(it) ? plainButton() : null);
  }

  /** The text of a card as the person asked for it: rendered Markdown, or the text exactly as it came (`wb-md is-plain`, mono). */
  const markdownOf = (value) => (plainChoice() ? h("div", { class: "wb-md is-plain", text: value || "" }) : renderMarkdown(value || ""));
  /** A long reply opens in place instead of scrolling inside the card (A-67, M-25): `name` keys the choice, kept while the card lives (a Plain text redraw keeps it). */
  const reply = (name, ...content) => replyView(content, { open: Boolean(state.replyOpen[name]), onToggle: (value) => { state.replyOpen[name] = value; } }).el;
  const text = (value, cls = "wb-card-body") => h("div", { class: cls }, reply("body", markdownOf(value)));

  // --- the controls ----------------------------------------------------------------------------------------------------------

  function buttons(extra) {
    const row = h("div", { class: "wb-card-actions" });
    const drawn = buttonsFor(state.item).filter(([word]) => {
      const ask = askOf(word);
      return ask === null || allow(ask[0], ask[1]);
    });
    drawn.forEach(([word, label, busyLabel], i) => {
      const blocked = state.item.kind === "review" && word === "released" && blockedChange(state.item);
      const mine = state.busy === word;
      const button = h("button", {
        class: `pui-btn ${i === 0 ? "pui-solid pui-theme" : "pui-surface pui-outline"} wb-card-button`, type: "button", "data-word": word,
        "aria-busy": mine ? "true" : null, "aria-disabled": blocked ? "true" : null, "aria-describedby": blocked ? `${uid}-blocked` : null,
      }, mine ? ring(true) : null, mine ? busyLabel : label);
      button.disabled = Boolean(state.busy) || Boolean(state.done);
      button.addEventListener("click", () => press(word));
      row.append(button);
    });
    if (extra) row.append(extra);
    if (state.busy && isJob(state.busy)) row.append(h("span", { class: "wb-working", role: "status", text: "Working..." }));
    return row.children.length ? row : null;
  }

  function isJob(word) {
    const kind = state.item.kind;
    return (kind === "question" && word === "route") || (kind === "effect" && word === "approved") || (kind === "plan" && word === "approved") || (kind === "acceptance" && word === "accepted") || (kind === "review" && word === "released");
  }

  function message() {
    if (!state.error) return null;
    const extra = state.error.gone ? h("a", { class: "pui-link pui-theme", href: env.links.parent ? env.links.parent() : router.cityHash(), text: "Back" }) : null;
    return notice(state.error.text, "error", extra);
  }

  function textarea(key, label, rows, hint, invalid) {
    const control = h("textarea", { class: "pui-input wb-field-input", rows: String(rows), "aria-keyshortcuts": key === "answer" ? "Control+Enter Meta+Enter" : null, "aria-invalid": invalid ? "true" : null });
    control.value = state.typed[key];
    control.disabled = Boolean(state.busy) || Boolean(state.done);
    control.addEventListener("input", () => { state.typed[key] = control.value; });
    control.addEventListener("keydown", (event) => {
      if (key === "answer" && (event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        press("answered");
      }
    });
    inputs[key] = control;
    return field(label, control, hint);
  }

  function noteInput() {
    const control = h("input", { class: "pui-input wb-field-input", type: "text" });
    control.value = state.typed.note;
    control.disabled = Boolean(state.busy) || Boolean(state.done);
    control.addEventListener("input", () => { state.typed.note = control.value; });
    inputs.note = control;
    return field(NOTE_LABEL, control);
  }

  function blockedChange(it) {
    const change = it.payload && it.payload.changeset;
    return Boolean(change && change.blocked);
  }

  // --- the kinds -------------------------------------------------------------------------------------------------------------

  function effectBody() {
    const it = state.item;
    // a tab stop with a name (K-5): the keyboard reaches the whole hash the approval sends
    const hash = h("code", { class: "wb-hash", "data-hash": "effect", tabindex: "0", role: "group", "aria-label": "Hash of this content" }, it.payload_sha256 || "");
    state.hashNode = hash;
    return [
      h("h3", { class: "wb-card-title", id: titleId, tabindex: "-1", text: it.title }),
      h("div", { class: "wb-card-hint", text: "Exact content of the publish (what will be sent):" }),
      h("pre", { class: "wb-pre", tabindex: "0", "aria-label": "Exact content of the publish" }, it.body || ""),
      h("div", { class: "wb-card-hint", text: "Hash of this content" }), hash,
      h("p", { class: "wb-card-line", text: "Nothing is sent before you approve this exact content." }),
      can("reject") ? noteInput() : null, message(), buttons(),
    ];
  }

  function acceptanceBody() {
    return [h("h3", { class: "wb-card-title", id: titleId, tabindex: "-1", text: state.item.title }), text(state.item.body), message(), buttons()];
  }

  function questionBody() {
    const it = state.item;
    const lost = isUnrecognised(it);
    return [h("h3", { class: "wb-card-title", id: titleId, tabindex: "-1", text: it.title }), text(it.body),
      lost ? replyDisclosure(it.payload.raw) : null, lost ? routeControls() : null,
      can("answer") ? textarea("answer", "Your answer", 3, h("small", { class: state.empty === "answer" ? "wb-hint is-error" : "wb-hint", text: state.empty === "answer" ? "Type an answer." : "Ctrl or Cmd plus Enter sends." }), state.empty === "answer") : null,
      message(), buttons()];
  }

  /** "Show the agent's reply": the planning agent's reply whole, as plain text (A-25). */
  function replyDisclosure(raw) {
    if (typeof raw !== "string" || !raw) return null;
    return h("details", { class: "wb-disclosure wb-verdict wb-raw-reply" }, h("summary", { class: "wb-summary", text: "Show the agent's reply" }),
      h("pre", { class: "wb-pre", tabindex: "0", "aria-label": "The planning agent's reply" }, raw));
  }

  /** A button of the unrecognised-route card, outside `actions`: it sends the request of its word. */
  function routeButton(word, label, busyLabel, theme, solid = false) {
    const mine = state.busy === word;
    const button = h("button", { class: `pui-btn ${theme} ${solid ? "pui-solid" : "pui-outline"} wb-card-button`, type: "button", "data-word": word, "aria-busy": mine ? "true" : null }, mine ? ring(true) : null, mine ? busyLabel : label);
    button.disabled = Boolean(state.busy) || Boolean(state.done);
    button.addEventListener("click", () => press(word));
    return button;
  }

  /** The two actions of a reply that named no route: "Choose a flow" (the list, then `route` with the flow) and "Cancel the request". */
  function routeControls() {
    const r = state.route;
    const parts = [h("div", { class: "wb-card-actions wb-route-actions" }, allow("route") ? routeButton("choose-flow", "Choose a flow", "Reading the flows...", "pui-theme") : null, routeButton("cancel-request", "Cancel the request", "Cancelling...", "pui-surface"))];
    if (r.open && r.flows === null) parts.push(h("div", { class: "wb-busy", role: "status", "aria-busy": "true" }, ring(true), h("span", { text: "Reading the flows..." })));
    if (r.open && r.flows !== null && can("route")) {
      const select = h("select", { class: "pui-input wb-field-input", "data-key": "flow", "aria-invalid": state.empty === "flow" ? "true" : null },
        h("option", { value: "", text: r.flows.length ? "Choose a flow..." : "The project has no flow" }),
        r.flows.map((f) => h("option", { value: f.flow, text: typeof f.title === "string" && f.title ? f.title : f.flow })));
      select.value = r.flow;
      select.disabled = Boolean(state.busy) || Boolean(state.done);
      select.addEventListener("change", () => { r.flow = select.value; });
      inputs.flow = select;
      parts.push(field("Flow", select, h("small", { class: state.empty === "flow" ? "wb-hint is-error" : "wb-hint", text: state.empty === "flow" ? "Choose a flow." : "The request is planned from this flow." })),
        h("div", { class: "wb-card-actions" }, routeButton("route", "Route with this flow", "Routing...", "pui-theme", true)));
    }
    return h("div", { class: "wb-route-controls" }, parts);
  }

  function pathRow(file, withOpen) {
    const link = withOpen && openable(file.path) ? h("a", { class: "pui-link pui-theme", href: env.links.open(state.item, file.path), "aria-label": `Open ${file.path}`, text: "Open" }) : null;
    return h("li", { class: "wb-path-row" }, h("code", { class: "wb-path", text: file.path }), file.reason ? h("span", { class: "wb-card-hint", text: String(file.reason) }) : null, link);
  }

  function reviewBody() {
    const it = state.item;
    const payload = it.payload || {};
    const returned = Array.isArray(payload.returned) ? payload.returned : [];
    const kept = Array.isArray(payload.kept) ? payload.kept : [];
    const parts = [h("h3", { class: "wb-card-title", id: titleId, tabindex: "-1", text: it.title }),
      h("div", { class: "wb-card-body" }, reply("body", markdownOf(it.body || "")))];
    if (returned.length || kept.length) {      // floor.html: the two lists of paths stand together in one small block
      parts.push(h("div", { class: "wb-ret" },
        returned.length ? h("span", { class: "wb-card-label", text: "Returned" }) : null, returned.length ? h("ul", { class: "wb-paths" }, returned.map((f) => pathRow(f, true))) : null,
        kept.length ? h("span", { class: "wb-card-label", text: "Kept" }) : null, kept.length ? h("ul", { class: "wb-paths" }, kept.map((f) => pathRow(f, false))) : null));
    }
    if (payload.ending) parts.push(h("p", { class: "wb-card-line" }, "Ending: ", ENDING[payload.ending] || String(payload.ending)));
    if (payload.why) parts.push(h("div", { class: "wb-card-body wb-muted", text: String(payload.why) }));
    const change = payload.changeset || {};
    if (change.error) parts.push(notice(String(change.error), "error"));
    if (change.blocked) {
      parts.push(h("div", { class: "wb-blocked", id: `${uid}-blocked` },
        h("strong", { class: "wb-blocked-title", text: "The change set is blocked: release refused" }),
        (change.refused || []).map((r) => h("div", { class: "wb-path-row" }, h("code", { class: "wb-path", text: r.path || "the whole set" }), h("span", { class: "wb-card-hint", text: String(r.reason || "") }))),
        h("span", { class: "wb-card-line", text: "Answer the review with a comment, or cancel the request." })));
    }
    parts.push(can("answer") ? textarea("comment", "Comment", 3, state.empty === "comment" ? h("small", { class: "wb-hint is-error", text: "Type a comment." }) : null, state.empty === "comment") : null, handOver(), message());
    // floor.html: "Record a verdict" is a plain line between the comment and the buttons
    if (it.run_id !== null && it.run_id !== undefined && allow("verdict")) parts.push(verdictDisclosure(it.run_id));
    parts.push(buttons());
    return parts;
  }

  /**
   * "Hand a file over" on the review card (A-30): the file goes to the task the review is about and travels with the answer into its next run.
   * It appears once the task is read and says it takes a file; for a task with the web, the runtime's line (what the open network can see) stands
   * above the control, before the file is chosen. In two steps (C-17): choosing a file sends nothing and shows its name with the button "Hand over to
   * task #n"; the button sends `handOver` and nothing else.
   */
  function handOver() {
    const drop = state.drop;
    if (!drop || drop.takes === false || typeof api().handOver !== "function") return null;
    if (!allow("hand-over")) return null;
    const input = h("input", { class: "pui-input wb-file", type: "file", "data-key": "hand-file" });
    input.disabled = Boolean(state.busy) || Boolean(state.done) || Boolean(state.handing);
    input.addEventListener("change", () => pickFile(input));
    const line = drop.web && typeof drop.line === "string" && drop.line ? h("p", { class: "wb-drop-line", role: "note", text: drop.line }) : null;
    const hint = h("span", { class: "wb-hint wb-muted wb-cur-sub", text: `To task #${state.item.task_id}. At most 25 MiB.` });
    const chooser = handChooser({ input, line, hint });
    chooser.button.disabled = input.disabled;
    return h("div", { class: "wb-hand wb-card-hand" },
      chooser.nodes.slice(0, 4),
      handOverStep(state.picked, state.item.task_id, () => handFile(), { disabled: Boolean(state.busy) || Boolean(state.done) || Boolean(state.handing), label: isMediaFile(state.picked) ? MEDIA_LABEL : undefined }),
      hint,
      h("span", { class: "wb-media-hint wb-muted wb-cur-sub", text: mediaHintText() }),      // a video is attached on the Mac, through the media route
      state.handing ? h("div", { class: "wb-busy", role: "status", "aria-busy": "true" }, ring(true), h("span", { text: state.progress ? "Uploading..." : "Sending..." })) : null,
      state.handing && state.progress ? state.progress.node : null,
      state.handed ? (state.handed.error ? notice(state.handed.text, "error") : h("p", { class: "wb-card-line", role: "status", text: state.handed.text })) : null);
  }

  /** Step one: a file was chosen. The page refuses what the service would refuse, else holds the file and shows its name and the button. Nothing is sent. */
  function pickFile(input) {
    const file = input.files && input.files[0];
    if (state.handing || state.busy || state.done) return;
    const refusal = file ? pickRefusal(file, fileRefusal, { may: can("media-in") }) : "";
    state.picked = file && !refusal ? file : null;
    state.handed = refusal ? { text: refusal, error: true } : null;
    render();
    const next = root.querySelector ? root.querySelector(".wb-hand-button") || root.querySelector("input.wb-file") : null;
    if (next) next.focus();      // the chooser was drawn again: the focus goes to the next step
  }

  /** Step two: the button. Sends the file held, to the review's task; a failure leaves the file held so that the button can be pressed again. */
  async function handFile() {
    const file = state.picked;
    const media = isMediaFile(file);
    if (!file || state.handing || state.busy || state.done || !can(media ? "media-in" : "hand-over")) return;
    const it = state.item;
    state.handing = true;
    state.handed = null;
    state.progress = media ? progressBar() : null;
    render();
    try {
      if (media) {      // a video, or a file over 25 MiB: its own bytes to the media route with a progress bar, never base64 (the Mac only)
        state.handed = { text: storedLine(await uploadRecording(api(), env.project, file, { bar: state.progress })) };
      } else {
        const bytes = new Uint8Array(await file.arrayBuffer());
        const result = await api().handOver(env.project, it.task_id, file.name, toBase64(bytes));
        state.handed = { text: `Handed over: ${result.path} (${result.bytes} bytes)` };
      }
      state.picked = null;
    } catch (e) {
      state.handed = { text: errorText(e), error: true };
    }
    state.handing = false;
    state.progress = null;
    render();
    const next = root.querySelector ? root.querySelector(".wb-hand-button") || root.querySelector("input.wb-file") : null;
    if (next) next.focus();
  }

  /** The review's task is read once for the file-drop line (`drop`: {web, takes, line}); a read that fails leaves the control out. */
  let dropAsked = false;
  async function loadDrop() {
    if (dropAsked || !env.task || state.item.kind !== "review" || state.item.task_id === null || state.item.task_id === undefined) return;
    dropAsked = true;
    try {
      const body = await env.task(state.item.task_id);
      state.drop = body && body.drop && typeof body.drop === "object" ? body.drop : null;
      if (state.drop && !state.done) render();
    } catch (e) {
      state.drop = null;
    }
  }

  function verdictDisclosure(runId) {
    const row = h("div", { class: "wb-verdicts" });
    for (const word of ["worked", "corrected", "failed"]) {
      const button = h("button", { class: "pui-btn pui-surface pui-outline wb-verdict-button", type: "button", "data-verdict": word, text: word });
      button.disabled = Boolean(state.busy) || Boolean(state.done) || Boolean(state.verdict && state.verdict.done);
      button.addEventListener("click", () => sendVerdict(word, runId));
      row.append(button);
    }
    return h("details", { class: "wb-disclosure wb-verdict" },
      h("summary", { class: "wb-summary", text: "Record a verdict" }), row,
      state.verdict ? (state.verdict.error ? notice(state.verdict.text, "error") : h("p", { class: "wb-card-line", role: "status", text: state.verdict.text })) : null);
  }

  function planBody() {
    const it = state.item;
    const payload = it.payload || {};
    const rows = planRows(payload);
    const waits = createWaitsBlock(payload, { disabled: Boolean(state.busy) || Boolean(state.done), checked: state.goAhead, can });
    state.waits = waits;
    if (waits && waits.withheld) allow("approve", "go-ahead");      // the boxes were left out: the line names it
    const hash = h("code", { class: "wb-hash", "data-hash": "plan", tabindex: "0", role: "group", "aria-label": "Plan hash" }, payload.plan_sha256 || "");   // a tab stop with a name (K-5)
    state.hashNode = hash;
    const table = h("table", { class: "pui-table wb-plan-table" },
      h("thead", {}, h("tr", {}, PLAN_COLUMNS.map(([, label]) => h("th", { scope: "col", text: label })))),
      h("tbody", {}, rows.map((r) => h("tr", {}, PLAN_COLUMNS.map(([key, label]) => h("td", { "data-label": label, class: key === "skill" ? "wb-skill" : null, text: r[key] }))))));
    return [
      h("h3", { class: "wb-card-title", id: titleId, tabindex: "-1", text: it.title }),
      h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Plan tasks" }, table),
      waits ? waits.el : null,
      h("div", { class: "wb-card-hint", text: limitsLine(payload) }),
      h("div", { class: "wb-card-hint", text: "Plan hash" }), hash,
      h("details", { class: "wb-disclosure wb-verdict" }, h("summary", { class: "wb-summary", text: "Plan as text" }), h("div", { class: "wb-card-body" }, reply("plan", markdownView(it.body || "", { name: "the plan", renderedLabel: "Plan as text", plainClass: "wb-pre" })))),
      can("reject") ? noteInput() : null, message(), buttons(),
    ];
  }

  function unknownBody() {
    const it = state.item;
    return [h("h3", { class: "wb-card-title", id: titleId, tabindex: "-1", text: it.title }), text(it.body),
      it.kind === "your_document" ? h("p", { class: "wb-card-line", text: "Delivering a document is not available on this page yet." }) : null];
  }

  function doneBody() {
    const done = state.done;
    const result = done.result && typeof done.result === "object" ? done.result : null;
    const payload = state.item.payload && typeof state.item.payload === "object" ? state.item.payload : {};
    const ids = [];        // a commit and a pull request are ids: mono
    const prose = [];      // a sentence is prose
    if (result) {
      if (result.commit) ids.push(`commit: ${result.commit}`);
      if (result.pull_request) ids.push(`pull request: ${typeof result.pull_request === "object" ? JSON.stringify(result.pull_request) : result.pull_request}`);
      if (state.item.kind === "question" && result.state && result.state.written === false && result.state.reason) prose.push(String(result.state.reason));
    }
    const kept = Array.isArray(payload.kept) ? payload.kept : [];
    if (kept.length) prose.push(`kept: ${kept.length} file${kept.length === 1 ? "" : "s"} in the run folder`);
    const folder = kept.length && typeof payload.run_dir === "string" ? commandBlock({ command: payload.run_dir, sentence: "Run folder", label: "Copy the path" }) : null;
    // The result is a block on its own line under the chip and the title (the done card wraps): a sentence never shares a row with the title (A-26).
    return h("div", { class: "wb-resolved wb-card-done", role: "status", tabindex: "-1" },
      chip(done.text, "pui-success pui-soft"), h("span", { class: "wb-muted wb-card-done-title", text: state.item.title }),
      ids.length || prose.length || folder
        ? h("div", { class: "wb-card-result" }, prose.map((l) => h("p", { class: "wb-card-line", text: l })), ids.map((l) => h("div", { class: "mono", text: l })), folder) : null);
  }

  function render() {
    const active = document.activeElement;
    const word = active && root.contains(active) && active.getAttribute ? active.getAttribute("data-word") : null;
    inputs = {};
    lacking = [];
    const it = state.item;
    let body;
    if (state.done) body = [doneBody()];
    else if (it.kind === "effect") body = effectBody();
    else if (it.kind === "acceptance") body = acceptanceBody();
    else if (it.kind === "question") body = questionBody();
    else if (it.kind === "review") body = reviewBody();
    else if (it.kind === "plan") body = planBody();
    else body = unknownBody();
    if (!state.done) body.push(withheldLine(lacking));
    if (state.done) fill(root, h("div", { class: "pui-card-content wb-card-content is-done" }, h("h3", { class: "wb-sr", id: titleId, text: it.title }), body));
    else fill(root, header(), h("div", { class: "pui-card-content wb-card-content" }, body));
    root.setAttribute("aria-busy", state.busy ? "true" : "false");
    if (word) {
      const next = root.querySelector ? root.querySelector(`[data-word="${word}"]`) : null;
      if (next && !next.disabled) next.focus();
    }
  }

  // --- the actions -----------------------------------------------------------------------------------------------------------

  async function press(word) {
    if (state.busy || state.done) return;
    const it = state.item;
    if (!permits(word)) return;      // the policy withholds it: no button draws it, and no key sends it either
    state.empty = null;
    let run;
    if (it.kind === "question" && word === "choose-flow") return openFlows();
    if (it.kind === "question" && word === "route") {
      if (!state.route.flow) return refuse("flow");
      run = () => api().route(env.project, it.task_id, { flow: state.route.flow });
    } else if (it.kind === "question" && word === "cancel-request") {
      run = () => api().cancel(env.project, it.task_id);
    } else if (it.kind === "question" && word === "answered") {
      if (!state.typed.answer.trim()) return refuse("answer");
      run = () => api().answer(env.project, it.id, state.typed.answer);
    } else if (it.kind === "review" && word === "answered") {
      if (!state.typed.comment.trim()) return refuse("comment");
      run = () => api().answer(env.project, it.id, state.typed.comment);
    } else if (it.kind === "review" && word === "released") {
      if (blockedChange(it)) return;   // the operation would refuse: nothing is sent from the page (the 409 stays the backstop)
      run = () => api().release(env.project, it.id);
    } else if (it.kind === "effect" && word === "approved") {
      const shown = state.hashNode ? state.hashNode.textContent : "";
      if (!shown || shown !== it.payload_sha256) {
        state.error = { text: "The hash shown is not the hash of this decision. Nothing was sent; the card is read again." };
        render();
        return reread();
      }
      run = () => api().approve(env.project, it.id, shown);
    } else if (it.kind === "plan" && word === "approved") {
      const shown = state.hashNode ? state.hashNode.textContent : "";
      if (!shown || shown !== (it.payload && it.payload.plan_sha256)) {
        state.error = { text: "The hash shown is not the hash of this plan. Nothing was sent; the card is read again." };
        render();
        return reread();
      }
      const ahead = state.waits ? state.waits.keys() : [];      // the boxes ticked "Go ahead", read at the moment of the click
      run = () => (ahead.length ? api().approve(env.project, it.id, shown, { goAhead: ahead }) : api().approve(env.project, it.id, shown));
    } else if (it.kind === "acceptance" && word === "accepted") {
      run = () => api().approve(env.project, it.id);
    } else if (word === "rejected") {
      const note = state.typed.note.trim() ? state.typed.note : undefined;
      run = () => api().reject(env.project, it.id, it.kind === "acceptance" ? undefined : note);
    } else {
      return;
    }
    state.busy = word;
    state.error = null;
    render();
    try {
      let result = await run();
      if (isJob(word) && result && typeof result === "object" && result.job) {
        const finished = await api().pollJob(result.job, 1000);
        if (finished.state === "failed") throw Object.assign(new Error(jobText(finished)), { job: true });
        result = finished.result;
      }
      if (word === "route" && result && result.routed === false) throw new Error((result.failure && result.failure.reason) ? `The router could not run: ${result.failure.reason}.` : "The request could not be planned.");
      state.busy = null;
      state.done = { text: DONE_TEXT[word] || `${format.kindWord(it.kind)} ${RESOLVED[word]}`, result, word };
      render();
      if (env.changed) env.changed(it.id, state.done);
    } catch (e) {
      state.busy = null;
      state.error = { text: errorText(e), gone: isGone(e) };
      render();
      if (isGone(e)) {
        if (env.gone) env.gone(it.id);
      } else {
        await reread();
      }
    }
  }

  /** "Choose a flow": show the list (read once with `flows`, only the flows that load). A read that fails is said on the card. */
  async function openFlows() {
    const r = state.route;
    r.open = true;
    state.error = null;
    render();
    if (r.flows !== null) return;
    try {
      const got = await api().flows(env.project);
      r.flows = (Array.isArray(got && got.flows) ? got.flows : []).filter((f) => f && typeof f.flow === "string" && !f.error);
    } catch (e) {
      r.open = false;
      state.error = { text: errorText(e) };
    }
    render();
  }

  function refuse(key) {
    state.empty = key;
    render();
    if (inputs[key] && inputs[key].focus) inputs[key].focus();
  }

  async function sendVerdict(word, runId) {
    if (state.busy || state.done || (state.verdict && state.verdict.done) || !can("verdict")) return;
    state.busy = "verdict";
    render();
    try {
      await api().verdict(env.project, runId, word);
      state.verdict = { text: `Verdict recorded: ${word}.`, done: true };
    } catch (e) {
      state.verdict = { text: errorText(e), error: true };
    }
    state.busy = null;
    render();
    const details = root.querySelector ? root.querySelector("details.wb-verdict") : null;
    if (details && details.setAttribute) details.setAttribute("open", "");
  }

  async function reread() {
    if (!env.reread) return;
    try {
      const fresh = await env.reread(state.item.id);
      if (fresh && fresh.status && fresh.status !== "open") {
        state.item = fresh;
        if (env.changed) env.changed(fresh.id, null);
        return;
      }
      if (fresh) state.item = fresh;
      render();
    } catch (e) {
      if (isGone(e) && env.gone) env.gone(state.item.id);
    }
  }

  // R-34: one choice for the session: when any card flips it, every card of the page draws its text again (the Floor's Inbox and the Lobby's)
  let seen = false;
  const stopListening = onPlainChoice(() => {
    if (root.isConnected) {
      seen = true;
      render();
    } else if (seen) stopListening();
  });
  render();
  loadDrop();
  return {
    el: root, id: item.id,
    /** Draw a fresher body of the same decision (typed text stays); a card in flight is not touched. */
    update(next) {
      if (state.busy || state.done) return;
      state.item = next;
      render();
    },
    focusTitle() {
      const node = root.querySelector ? root.querySelector(`#${titleId}`) : null;
      if (node && node.focus) node.focus();
    },
    isDone() {
      return Boolean(state.done);
    },
    isBusy() {
      return Boolean(state.busy);
    },
    /** The policy changed (js/permissions.js): draw again with what the page may do now; typed text stays. */
    redraw() {
      if (!state.done) render();
    },
    outcome() {
      return state.done;
    },
    item() {
      return state.item;
    },
  };
}

/**
 * The request line (a badge, "Request #16: title", its state chip, and "Cancel request") and its dialog. request is a row of
 * `status.requests[]` {id, title, state, tasks}; env as above plus {words(state)}. Returns {el, dialog, update(request)}.
 */
export function createRequestLine(request, env) {
  counter += 1;
  const uid = `wb-request-${counter}`;
  let current = request;
  let busy = false;
  let error = null;
  const el = h("div", { class: "wb-request-line" });
  const dialog = h("dialog", { class: "pui-modal wb-cancel-dialog", "aria-labelledby": `${uid}-title` });
  let opener = null;
  dialog.addEventListener("close", () => {
    if (opener && opener.isConnected) opener.focus();
  });

  function drawDialog() {
    const keep = h("button", { class: "pui-btn pui-surface pui-outline", type: "button", text: "Keep it" });
    const go = h("button", { class: "pui-btn pui-error pui-outline", type: "button", "aria-busy": busy ? "true" : null }, busy ? ring(true) : null, busy ? "Cancelling..." : "Cancel request");
    keep.disabled = busy;
    go.disabled = busy;
    keep.addEventListener("click", () => dialog.close());
    go.addEventListener("click", async () => {
      if (busy) return;
      busy = true;
      error = null;
      drawDialog();
      try {
        await env.api.cancel(env.project, current.id);
        busy = false;
        dialog.close();
        if (env.changed) env.changed(current.id, { text: `Request ${current.id} cancelled` });
      } catch (e) {
        busy = false;
        error = errorText(e);
        drawDialog();
      }
    });
    fill(dialog, h("div", { class: "pui-card wb-card" },
      h("div", { class: "pui-card-content wb-card-content" },
        h("strong", { class: "wb-card-title", id: `${uid}-title`, text: "Cancel this request and what is still open under it?" }),
        h("div", { class: "wb-card-hint", text: `Request #${current.id}: ${current.title || ""} · ${cancelCount(current.tasks)}` }),
        error ? notice(error, "error") : null,
        h("div", { class: "wb-card-actions is-end" }, keep, go))));
    if (dialog.open && keep.focus) keep.focus();
  }

  function draw() {
    const open = h("button", { class: "pui-btn pui-link pui-error wb-cancel-link", type: "button", text: "Cancel request" });
    open.addEventListener("click", () => {
      opener = open;
      error = null;
      drawDialog();
      dialog.showModal();
      const keep = dialog.querySelector ? dialog.querySelector("button") : null;
      if (keep && keep.focus) keep.focus();
    });
    fill(el, h("span", { class: "pui-badge pui-muted pui-soft pui-rounded-full", text: `#${current.id}` }),
      h("span", { text: `Request #${current.id}: ${current.title || ""}` }), chip(env.words ? env.words(current.state) : current.state, "pui-muted pui-soft", "11"),
      open, dialog);
    el.hidden = current.state === "done" || current.state === "cancelled";
  }

  draw();
  return {
    el, dialog,
    update(next) {
      if (dialog.open) return;
      current = next;
      draw();
    },
  };
}
