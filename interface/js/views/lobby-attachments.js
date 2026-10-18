// The files people sent through a messaging app (package ATT-1), a section of the Building's panel: the files held for an answer, each with what it is, the source it
// would become and when it expires, "Add" and "Discard", and the latest decisions. A held file is in the project's data folder and nowhere else; adding it makes a
// version of a source (the same container, credential scan and immutable version as any import), and a row never says who sent it. The page decides nothing: the
// service lists, adds and discards, and its sentence for a refusal is shown as it came. The controls are drawn only when the page may (js/permissions.js); the section
// is hidden while nothing is held and nothing was decided lately. It lives with the Lobby's modules because a write may not be sent from the Building itself
// (test_interface_files.py); the Building only places it. Text from the service goes in as text.

import { h } from "../dom.js";
import { failureText } from "../cards/plan-rows.js";
import { can as pageMay } from "../permissions.js";

export const HEAD = "Files from messaging apps";
export const LEAD = "A file sent from a messaging app waits here until you add it as a source or discard it. It is not read by any task until you add it.";
const REREAD_MS = 15000;      // the list is read again when it is older than this, when the page reloads (the store changed: a file arrived), and after every write
const LATEST = 5;             // how many of the latest decisions are shown

/** A size for a person: `812 bytes`, `3.5 KiB`, `12.0 MiB`. */
export function sizeWords(count) {
  const n = Number(count);
  if (!Number.isFinite(n) || n < 0) return "";
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MiB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KiB`;
  return `${n} bytes`;
}

/** Where a held file came from: `telegram, profile staff` (the profile only when there is one). */
export function fromWords(row) {
  const profile = row && row.profile && row.profile !== "default" ? `, profile ${row.profile}` : "";
  return `${row && row.platform ? row.platform : "a messaging app"}${profile}`;
}

/** What adding a held file does: a new source, or the next version of the one it names. */
export function becomesWords(row) {
  const id = row && row.target ? row.target : "";
  return row && row.label === "refresh" ? `a new version of the source ${id}` : `the new source ${id}`;
}

/** The line of a decision that is over: `added as <id>, version <n>`, `refused (code)`, `discarded`, `expired`. */
export function decidedWords(row) {
  if (!row) return "";
  if (row.status === "added") return `added as ${row.source_id}, version ${row.version}`;
  if (row.status === "refused") return `refused${row.code ? ` (${row.code})` : ""}`;
  return String(row.status || "");
}

/**
 * env: {api (the client), project (getter), entry() (the GET /projects entry, for the policy), refresh()}. Returns {el, update(detail, shown)}.
 */
export function createAttachments(env) {
  const head = h("h3", { class: "wb-steps-head", text: HEAD });
  const lead = h("p", { class: "wb-steps-line", text: LEAD });
  const list = h("ul", { class: "wb-at-list", "aria-label": "Files waiting for your answer" });
  const latest = h("ul", { class: "wb-at-latest", "aria-label": "Latest decisions" });
  const note = h("p", { class: "wb-steps-note wb-at-note", role: "status" });
  const error = h("div", { class: "wb-form-error" });
  const el = h("section", { class: "wb-steps-sec wb-at-sec", hidden: true }, head, lead, list, note, error, latest);
  let data = null;
  let readAt = 0;
  let reading = false;
  let shown = false;
  let busy = false;
  let seen;                // the page's reload stamp last seen
  const may = (op) => pageMay(env.entry ? env.entry() : null, op);

  function fail(e) {
    error.replaceChildren(h("p", { class: "notice pui-soft pui-error wb-notice-card", role: "alert", text: failureText(e) }));
  }

  async function load(force = false) {
    if (reading || !shown || !may("attachments") || !(force || Date.now() - readAt >= REREAD_MS)) return;
    reading = true;
    try {
      data = await env.api.attachments(env.project);
      readAt = Date.now();
    } catch (e) {
      fail(e);
    }
    reading = false;
    draw();
  }

  async function decide(call, row) {
    if (busy) return;
    busy = true;
    error.replaceChildren();
    note.textContent = "";
    try {
      const done = await call(env.project, row.id);
      note.textContent = done && typeof done.reply === "string" ? done.reply : "";
      if (env.refresh) await env.refresh();
    } catch (e) {
      fail(e);
    }
    busy = false;
    readAt = 0;
    await load(true);
  }

  function item(row) {
    const li = h("li", { class: "wb-at-item" });
    const what = h("p", { class: "wb-at-name" }, h("strong", { text: row.name }), ` (${row.kind || "file"}, ${sizeWords(row.bytes)})`);
    const line = h("p", { class: "wb-steps-note wb-at-line", text: `From ${fromWords(row)}. Adding it makes ${becomesWords(row)}.${row.expires_at ? ` It is deleted on ${String(row.expires_at).slice(0, 10)} if you do not answer.` : ""}` });
    const actions = h("div", { class: "wb-rt-actions" });
    if (may("attachment-add")) {
      const add = h("button", { class: "pui-btn pui-surface pui-outline wb-small-button wb-at-add", type: "button", text: "Add as a source" });
      add.disabled = busy;
      add.addEventListener("click", () => decide((p, id) => env.api.attachmentAdd(p, id), row));
      actions.append(add);
    }
    if (may("attachment-discard")) {
      const discard = h("button", { class: "pui-btn pui-surface pui-outline wb-small-button wb-at-discard", type: "button", text: "Discard" });
      discard.disabled = busy;
      discard.addEventListener("click", () => decide((p, id) => env.api.attachmentDiscard(p, id), row));
      actions.append(discard);
    }
    li.append(what, line, actions);
    return li;
  }

  function draw() {
    const held = data && Array.isArray(data.held) ? data.held : [];
    const recent = data && Array.isArray(data.recent) ? data.recent.slice(0, LATEST) : [];
    el.hidden = !shown || (!held.length && !recent.length && !error.children.length && !note.textContent);
    list.replaceChildren(...held.map(item));
    latest.replaceChildren(...recent.map((row) => h("li", { class: "wb-at-done", text: `${row.name}: ${decidedWords(row)}` })));
  }

  return {
    el,
    /** detail: the project's entry of the snapshot; shown: whether the panel draws the section at all (the project is accepted); stamp: the page's reload stamp, which moves when the store changed. */
    update(detail, isShown, stamp) {
      const moved = stamp !== undefined && stamp !== seen;
      seen = stamp;
      shown = Boolean(isShown && detail);
      if (!shown) {
        data = null;
        error.replaceChildren();
        note.textContent = "";
      }
      draw();
      if (shown) load(moved);
    },
  };
}
