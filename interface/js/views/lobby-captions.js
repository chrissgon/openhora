// The caption review of a new video (package V1c-2), a dialog the Videos section opens: the words by caption chunk, the retakes, the beats and the animations of the
// video, and "Add an animation" from the catalogue. Each action sends exactly one closed edit (views/lobby-captions-model.js builds it) with the revision the page read;
// a stale revision is read again and said, and nothing is queued or retried by itself. At the review, "Continue" answers the review decision and runs the video; at the
// delivery card an edit already answered it by code and "Render again" runs the video. The page decides nothing: the service checks every edit, and its sentence for a
// refusal is shown as it came. No animation is drawn here (the sample of a block is text). The still comes only from this computer's own page and is shown from a blob
// URL. Every control is drawn only when the page may (js/permissions.js) and asks again when clicked. It lives with the Lobby's modules because a write may not be sent
// from the Building itself (test_interface_files.py); the Building only places it. Text from the service goes in as text.

import { h } from "../dom.js";
import { failureText } from "../cards/plan-rows.js";
import { can as pageMay } from "../permissions.js";
import { hostOf, onLoopback, LAN_MEDIA } from "../cards/deliver.js";
import {
  selection, grow, shrink, sameSegment, editOf, retakeEdit, anchorEdit, clearAnchor, overlayEdit, removeAnimation, addAnimation,
  fieldsOf, paramsOf, WHY_TEXT, canEdit,
} from "./lobby-captions-model.js";

export const TITLE = "Check the captions";
export const TERMINAL_LINE = "Change the face box, the cover, the theme or a slot in the terminal: python3 runtime/cli.py captions-edit";
export const STALE_TEXT = "The captions changed; they were read again.";
export const NO_REVIEW = "There is no review waiting for this video.";
export const GATE_LINE = "The delivery card was answered by your edit: the video renders again when you run it.";
export const READ_ONLY_LINE = "This video is not waiting for a review: its captions are read-only.";
const POLL_MS = 1000;
const OPTIONAL_HINT = "Optional; the renderer checks it";

/** The words of the caption counts line. */
export function countsText(counts) {
  const c = counts || {};
  return `${c.words || 0} words, ${c.edited || 0} edited, ${c.retakes || 0} retakes, ${c.beats || 0} beats, ${c.animations || 0} animations`;
}

/** "Words a to b" for a range. */
export function rangeText(sel) {
  return `Words ${sel.from} to ${sel.to}`;
}

/** True when the service refused an edit because the captions moved on since the page read them. */
export function isStale(error) {
  const word = error && typeof error.word === "string" ? error.word : "";
  const message = error && typeof error.message === "string" ? error.message : "";
  return word === "stale_revision" || /stale_revision|captions changed/i.test(message);
}

/** The sentence for the end of a run job, in the words the Videos section uses. */
export function resultText(job) {
  if (job && job.state === "failed") return (job.error && job.error.message) || "The step failed.";
  const result = (job && job.result) || {};
  if (result.started === false) return `The video is ready to run: ${result.reason || ""}`.trim();
  if (result.failed) return `The step failed: ${result.code}${result.field ? ` (${result.field})` : ""}`;
  return "The captions are ready to check.";
}

/** Whether the run job ended without a problem: the dialog closes only then. */
export function resultOk(job) {
  if (!job || job.state === "failed") return false;
  const result = job.result || {};
  return result.started !== false && !result.failed;
}

/** One sample of a catalogue block as a line: the values of its parameters, joined; an empty sample has no line. */
function sampleLine(entry) {
  const first = entry && Array.isArray(entry.samples) ? entry.samples[0] : null;
  let values = [];
  if (first && typeof first === "object") values = Object.values(first);
  else if (first !== null && first !== undefined) values = [first];
  const text = values.filter((v) => v !== null && v !== undefined && typeof v !== "object").map(String).join(", ");
  return text ? `Sample: ${text}` : "";
}

function valueText(value) {
  if (value === null || value === undefined) return "not set";
  return typeof value === "string" ? value : JSON.stringify(value);
}

/**
 * env: {api (the client), project (getter), refresh(), entry() (the GET /projects entry, for the policy), host() (tests: the page's host name)}.
 * Returns {el, open(task, mode)}; `el` is appended to the document once by the Building.
 */
export function createCaptionReview(env) {
  const titleId = "wb-cr-title";
  const heading = h("h3", { class: "wb-card-title wb-cr-title", id: titleId, text: TITLE });
  const body = h("div", { class: "wb-cr-body" });
  const card = h("div", { class: "pui-card wb-dialog-card" }, h("div", { class: "pui-card-content wb-dialog-content wb-cr-content" }, heading, body));
  const el = h("dialog", { class: "pui-modal wb-dialog wb-cr-dialog", "aria-labelledby": titleId }, card);

  let task = null;
  let argMode = null;
  let data = null;             // the answer of captions-read
  let readError = "";
  let loading = false;
  let sel = null;              // {from, to}
  let fieldText = null;        // what the person typed in the word field; null = the words' own text
  let edited = false;          // an edit was saved in this dialog
  let busy = false;
  let notice = "";             // a plain line ("The captions changed...")
  let failure = "";            // the sentence of a refusal, as it came
  let stillUrl = "";
  let stillLine = "";
  let catalogue = null;        // the answer of video-catalogue, read once per open
  let catalogueOpen = false;
  let addFor = null;           // the catalogue entry whose parameter form is open
  let typed = {};
  let formProblem = "";
  let focusKey = "";
  let generation = 0;          // changes at every open and close: an answer of an earlier one is dropped
  let control = null;          // AbortController of the polls of this open
  const refs = new Map();
  const may = (op) => pageMay(env.entry ? env.entry() : null, op);
  const loopback = () => onLoopback(hostOf(env));
  const modeNow = () => (data && "mode" in data ? data.mode : argMode);
  const project = () => env.project;
  const editable = () => Boolean(data) && canEdit(modeNow()) && may("captions-edit");

  function revokeStill() {
    if (stillUrl) URL.revokeObjectURL(stillUrl);
    stillUrl = "";
  }

  function cleanup() {
    generation += 1;
    if (control) control.abort();
    control = null;
    revokeStill();
    busy = false;
  }

  function close() {
    cleanup();
    if (el.open !== false && typeof el.close === "function") el.close();
  }

  el.addEventListener("close", cleanup);
  el.addEventListener("cancel", (event) => {
    if (busy) event.preventDefault();      // Escape closes unless a send is in flight
  });

  function button(label, onClick, options = {}) {
    const b = h("button", { class: `pui-btn pui-surface pui-outline wb-small-button wb-cr-button${options.extra ? ` ${options.extra}` : ""}`, type: "button", text: label });
    b.disabled = Boolean(options.disabled) || (busy && !options.always);
    if (busy && options.busyLabel) b.setAttribute("aria-busy", "true");
    b.addEventListener("click", onClick);
    if (options.key) refs.set(options.key, b);
    return b;
  }

  function section(title, ...children) {
    return h("section", { class: "wb-cr-sec" }, h("h4", { class: "wb-cr-head", text: title }), ...children);
  }

  function wordOf(index) {
    return data.view.words.find((w) => w.index === index);
  }

  function inSel(index) {
    return Boolean(sel) && index >= sel.from && index <= sel.to;
  }

  // ---- reading ---------------------------------------------------------------------------------------------------------------------------

  async function loadStill(mine) {
    stillLine = "";
    if (!data || data.still === null || data.still === undefined) return;
    if (!loopback()) {
      stillLine = LAN_MEDIA;
      return;
    }
    if (!may("video-still")) return;
    try {
      const blob = await env.api.videoStill(project(), task, { signal: control ? control.signal : undefined });
      if (mine !== generation) return;
      revokeStill();
      stillUrl = URL.createObjectURL(blob);
    } catch (e) {
      if (mine === generation) stillLine = failureText(e);
    }
  }

  async function read(keep) {
    const mine = generation;
    loading = true;
    try {
      const answer = await env.api.captionsRead(project(), task, { signal: control ? control.signal : undefined });
      if (mine !== generation) return;
      data = answer;
      readError = "";
      const words = data && data.view ? data.view.words : [];
      const there = (i) => words.some((w) => w.index === i);
      if (!(keep && sel && there(sel.from) && there(sel.to))) {
        sel = null;
        fieldText = null;
      }
      revokeStill();
      await loadStill(mine);
    } catch (e) {
      if (mine !== generation) return;
      data = null;
      readError = failureText(e);
    }
    if (mine !== generation) return;
    loading = false;
    draw();
  }

  async function readCatalogue() {
    if (catalogue) return;
    if (!may("video-catalogue")) {
      failure = "The page may not read the catalogue.";
      return;
    }
    const mine = generation;
    try {
      const answer = await env.api.videoCatalogue(project(), { signal: control ? control.signal : undefined });
      if (mine === generation) catalogue = answer;
    } catch (e) {
      if (mine === generation) failure = failureText(e);
    }
  }

  // ---- sending ---------------------------------------------------------------------------------------------------------------------------

  async function sendEdit(edit) {
    if (busy || !edit || !editable()) return;
    const mine = generation;
    busy = true;
    failure = "";
    notice = "";
    draw();
    try {
      await env.api.captionsEdit(project(), task, data.view.revision, [edit]);
      if (mine !== generation) return;
      edited = true;
      addFor = null;
      catalogueOpen = false;
      formProblem = "";
      busy = false;
      await read(true);
      return;
    } catch (e) {
      if (mine !== generation) return;
      failure = isStale(e) ? "" : failureText(e);
      if (isStale(e)) {
        notice = STALE_TEXT;
        sel = null;
        fieldText = null;
        busy = false;
        await read(false);
        return;
      }
    }
    busy = false;
    draw();
  }

  async function runJob(call) {
    const started = await call();
    return env.api.pollJob(started.job, POLL_MS, { signal: control ? control.signal : undefined });
  }

  async function continueVideo() {
    if (busy || modeNow() !== "review" || !may("answer") || !may("video-run")) return;
    const mine = generation;
    busy = true;
    failure = "";
    notice = "";
    draw();
    let ok = false;
    try {
      const listed = await env.api.pending(project());
      const rows = Array.isArray(listed) ? listed : (listed && Array.isArray(listed.pending) ? listed.pending : []);
      const row = rows.find((r) => r && r.task_id === task && r.kind === "question");
      if (mine !== generation) return;
      if (!row) {
        notice = NO_REVIEW;
      } else {
        await env.api.answer(project(), row.id, "continue");
        if (mine !== generation) return;
        const job = await runJob(() => env.api.videoRun(project(), task));
        if (mine !== generation) return;
        notice = resultText(job);
        ok = resultOk(job);
      }
    } catch (e) {
      if (mine !== generation) return;
      failure = failureText(e);
    }
    busy = false;
    if (env.refresh) await env.refresh();
    if (mine !== generation) return;
    if (ok) {
      close();
      return;
    }
    draw();
  }

  async function renderAgain() {
    if (busy || !may("video-run")) return;
    const mine = generation;
    busy = true;
    failure = "";
    notice = "";
    draw();
    try {
      const job = await runJob(() => env.api.videoRun(project(), task));
      if (mine !== generation) return;
      notice = resultText(job);
    } catch (e) {
      if (mine !== generation) return;
      failure = failureText(e);
    }
    busy = false;
    if (env.refresh) await env.refresh();
    if (mine !== generation) return;
    draw();
  }

  // ---- drawing ---------------------------------------------------------------------------------------------------------------------------

  function wordsSection(view) {
    const canPick = editable();
    const row = (indices) => {
      const box = h("div", { class: "wb-cr-words" });
      for (const index of indices) {
        const w = wordOf(index);
        if (!w) continue;
        const classes = ["wb-cr-word"];
        if (w.left_out) classes.push("wb-cr-left-out");
        if (w.estimated) classes.push("wb-cr-estimated");
        if (w.edited) classes.push("wb-cr-edited");
        const notes = [];
        if (w.left_out) notes.push(`left out of the captions (${w.left_out})`);
        if (w.estimated) notes.push("its timing is estimated");
        if (w.edited) notes.push("you edited this word");
        const attrs = { class: classes.join(" "), title: notes.length ? `Word ${w.index}: ${notes.join(", ")}` : `Word ${w.index}` };
        if (!canPick) {
          box.append(h("span", attrs, w.text));
          continue;
        }
        const b = h("button", { ...attrs, type: "button", "aria-pressed": String(inSel(w.index)) }, w.text);
        b.disabled = busy;
        b.addEventListener("click", () => {
          if (busy || !editable()) return;
          sel = selection(sel, w.index, view.words);
          fieldText = null;
          focusKey = `word-${w.index}`;
          draw();
        });
        refs.set(`word-${w.index}`, b);
        box.append(b);
      }
      return box;
    };
    const shown = new Set();
    const rows = [];
    for (const chunk of view.chunks || []) {
      const list = Array.isArray(chunk.words) ? chunk.words : [];
      list.forEach((i) => shown.add(i));
      rows.push(row(list));
    }
    const rest = view.words.map((w) => w.index).filter((i) => !shown.has(i));
    const parts = [...rows];
    if (rest.length) parts.push(h("p", { class: "wb-steps-note wb-cr-note", text: "Left out of the captions:" }), row(rest));
    if (!view.words.length) parts.push(h("p", { class: "wb-steps-note wb-cr-note", text: "There are no words." }));
    if (canPick) parts.push(selectionTools(view));
    return section("Words", ...parts);
  }

  function selectionTools(view) {
    const tools = h("div", { class: "wb-cr-tools" });
    if (!sel) {
      tools.append(h("p", { class: "wb-steps-note wb-cr-note", text: "Select a word to change it, merge it with the next, or anchor a beat or an animation to it." }));
      return tools;
    }
    const single = sel.from === sel.to;
    const own = view.words.filter((w) => w.index >= sel.from && w.index <= sel.to).map((w) => w.text).join(" ");
    const value = fieldText === null ? own : fieldText;
    tools.append(h("p", { class: "wb-cr-range", role: "status", text: rangeText(sel) }));
    tools.append(h("div", { class: "wb-cr-actions" },
      button("One more word", () => { sel = grow(sel, view.words); fieldText = null; focusKey = "grow"; draw(); }, { key: "grow" }),
      button("One word less", () => { sel = shrink(sel); fieldText = null; focusKey = "shrink"; draw(); }, { key: "shrink" })));
    const mergeable = !single && sameSegment(sel, view.words);
    if (single || mergeable) {
      const field = h("input", { class: "pui-input wb-field-input wb-cr-field", type: "text", value, "aria-label": single ? "Text of the word" : "Text of the merged words" });
      field.value = value;
      field.disabled = busy;
      field.addEventListener("input", () => { fieldText = field.value; });
      const actions = h("div", { class: "wb-cr-actions" });
      if (single) {
        actions.append(
          button("Save the word", () => sendEdit(editOf("edit", sel, view.words, fieldText === null ? own : fieldText))),
          button("Remove the word", () => sendEdit(editOf("delete", sel, view.words))));
      } else {
        actions.append(button("Merge the words", () => sendEdit(editOf("merge", sel, view.words, fieldText === null ? own : fieldText))));
      }
      tools.append(field, actions);
      if (single) tools.append(h("p", { class: "wb-steps-note wb-cr-note", text: "A text with spaces splits the word into several." }));
    } else {
      tools.append(h("p", { class: "wb-steps-note wb-cr-note", text: "These words are in different segments: they cannot be merged." }));
    }
    return tools;
  }

  function retakesSection(view) {
    if (!view.retakes.length) return null;
    const list = h("ul", { class: "wb-cr-list", "aria-label": "Retakes" });
    for (const r of view.retakes) {
      const li = h("li", { class: "wb-cr-item" },
        h("p", { class: "wb-cr-line", text: `Retake ${r.id}: ${r.kind}, ${r.seconds} s, words ${r.word_from} to ${r.word_to}${r.confirmed ? ", cut" : ", kept"}` }));
      if (editable()) li.append(h("div", { class: "wb-cr-actions" }, button(r.confirmed ? "Keep it" : "Cut it", () => sendEdit(retakeEdit(r.id, !r.confirmed)))));
      list.append(li);
    }
    return section("Retakes", list);
  }

  function beatWords(b) {
    const span = b.word_from === null || b.word_from === undefined ? "" : ` over words ${b.word_from} to ${b.word_to}`;
    const status = [];
    if (b.anchored) status.push(`anchored${span}`);
    else if (b.matched) status.push(`matched${span}`);
    else if (b.below_threshold) status.push("below the threshold: no words matched");
    else status.push("not matched");
    if (b.dropped) status.push("overlay dropped");
    return status.join(", ");
  }

  function beatsSection(view) {
    if (!view.beats.length) return null;
    const list = h("ul", { class: "wb-cr-list", "aria-label": "Beats" });
    for (const b of view.beats) {
      const score = typeof b.score === "number" ? `, score ${b.score.toFixed(2)}` : "";
      const li = h("li", { class: "wb-cr-item" }, h("p", { class: "wb-cr-line", text: `Beat ${b.beat}: ${b.preset}${score}; ${beatWords(b)}` }));
      if (editable()) {
        const actions = h("div", { class: "wb-cr-actions" });
        if (sel) actions.append(button("Anchor to the selected words", () => sendEdit(anchorEdit(b.beat, sel))));
        if (b.anchored) actions.append(button("Clear the anchor", () => sendEdit(clearAnchor(b.beat))));
        actions.append(button(b.dropped ? "Keep the overlay" : "Drop the overlay", () => sendEdit(overlayEdit(b.beat, !b.dropped))));
        li.append(actions);
      }
      list.append(li);
    }
    return section("Beats", list);
  }

  function overlapOf(view, a) {
    const hit = view.beats.find((b) => !b.dropped && b.word_from !== null && b.word_to !== null && a.word_from !== null
      && b.word_from <= a.word_to && b.word_to >= a.word_from);
    return hit ? `, overlaps beat ${hit.beat}` : ", overlaps a beat";
  }

  function animationsSection(view) {
    const parts = [];
    if (view.animations.length) {
      const list = h("ul", { class: "wb-cr-list", "aria-label": "Animations" });
      for (const a of view.animations) {
        const text = `${a.block} over words ${a.word_from} to ${a.word_to}${a.lost ? ", lost" : ""}${a.overlaps_beat ? overlapOf(view, a) : ""}`;
        const li = h("li", { class: "wb-cr-item" }, h("p", { class: "wb-cr-line", text }));
        if (editable()) li.append(h("div", { class: "wb-cr-actions" }, button("Remove", () => sendEdit(removeAnimation(a.id)))));
        list.append(li);
      }
      parts.push(list);
    } else {
      parts.push(h("p", { class: "wb-steps-note wb-cr-note", text: "No animation yet." }));
    }
    if (editable()) parts.push(addSection(view));
    return section("Animations", ...parts);
  }

  function addSection(view) {
    const box = h("div", { class: "wb-cr-add" });
    const max = catalogue && Number.isFinite(catalogue.animations_max) ? catalogue.animations_max : null;
    if (max !== null && view.counts.animations >= max) {
      box.append(h("p", { class: "wb-steps-note wb-cr-note", text: `This video has the most animations it can have (${max}).` }));
      return box;
    }
    box.append(h("div", { class: "wb-cr-actions" }, button(catalogueOpen ? "Hide the catalogue" : "Add an animation", async () => {
      if (busy) return;
      if (catalogueOpen) {
        catalogueOpen = false;
        addFor = null;
        draw();
        return;
      }
      catalogueOpen = true;
      draw();
      await readCatalogue();
      draw();
    })));
    if (catalogueOpen && catalogue) box.append(catalogueView(view));
    return box;
  }

  function catalogueView(view) {
    const blocks = Array.isArray(catalogue.blocks) ? catalogue.blocks : [];
    const order = [...blocks.filter((b) => b.addable), ...blocks.filter((b) => !b.addable)];
    const list = h("ul", { class: "wb-cr-list wb-cr-catalogue", "aria-label": "Animation catalogue" });
    for (const entry of order) {
      const li = h("li", { class: "wb-cr-item" }, h("p", { class: "wb-cr-line" }, h("strong", { text: entry.name })));
      if (entry.use_when) li.append(h("p", { class: "wb-steps-note wb-cr-note", text: entry.use_when }));
      const sample = sampleLine(entry);
      if (sample) li.append(h("p", { class: "wb-steps-note wb-cr-note", text: sample }));
      if (entry.addable) {
        li.append(h("div", { class: "wb-cr-actions" }, button("Use this", () => {
          if (busy) return;
          addFor = entry;
          typed = {};
          formProblem = "";
          draw();
        })));
        if (addFor && addFor.name === entry.name) li.append(paramForm(view, entry));
      } else {
        li.append(h("p", { class: "wb-steps-note wb-cr-why", text: WHY_TEXT[entry.why] || "It cannot be added now." }));
      }
      list.append(li);
    }
    return list;
  }

  function paramForm(view, entry) {
    const fields = fieldsOf(entry);
    const form = h("div", { class: "wb-cr-form" });
    if (fields.unsupported) {
      form.append(h("p", { class: "wb-steps-note wb-cr-why", text: WHY_TEXT.slot }));
      return form;
    }
    form.append(h("p", { class: "wb-cr-range", text: sel ? `Over ${rangeText(sel).toLowerCase()}` : "Select the words first" }));
    for (const f of fields) {
      const label = h("label", { class: "wb-cr-label" }, `${f.name}${f.required ? " (required)" : ""}`);
      let input;
      if (f.type === "choice") {
        input = h("select", { class: "wb-select wb-cr-field" }, ...(f.required ? [] : [h("option", { value: "" }, "(none)")]), ...f.values.map((v) => h("option", { value: v }, v)));
        input.value = typed[f.name] !== undefined ? typed[f.name] : (f.required && f.values.length ? f.values[0] : "");
        if (f.required && typed[f.name] === undefined && f.values.length) typed[f.name] = f.values[0];
      } else {
        input = h("input", { class: "pui-input wb-field-input wb-cr-field", type: f.type === "number" ? "number" : "text", ...(f.type === "text" && f.max ? { maxlength: String(f.max) } : {}) });
        input.value = typed[f.name] !== undefined ? typed[f.name] : "";
      }
      input.disabled = busy;
      const update = () => { typed[f.name] = input.value; };
      input.addEventListener("input", update);
      input.addEventListener("change", update);
      label.append(input);
      form.append(label);
      if (f.type === "icon" || f.type === "color") form.append(h("p", { class: "wb-steps-note wb-cr-note", text: OPTIONAL_HINT }));
      if (f.type === "text" && f.maxItems) form.append(h("p", { class: "wb-steps-note wb-cr-note", text: `Up to ${f.maxItems} parts, separated by " | ".` }));
    }
    if (formProblem) form.append(h("p", { class: "wb-form-error wb-cr-problem", role: "alert", text: formProblem }));
    form.append(h("div", { class: "wb-cr-actions" }, button("Add the animation", () => {
      if (busy || !sel || !editable()) return;
      const made = paramsOf(fields, typed);
      if (made.problem) {
        formProblem = made.problem;
        draw();
        return;
      }
      formProblem = "";
      sendEdit(addAnimation(entry.name, made.params, sel));
    }, { disabled: !sel })));
    return form;
  }

  function stillSection() {
    if (!data || data.still === null || data.still === undefined) return null;
    const parts = [];
    if (stillUrl) parts.push(h("img", { class: "wb-cr-still", src: stillUrl, alt: "The still of the recording, with the face box" }));
    if (stillLine) parts.push(h("p", { class: "wb-steps-note wb-cr-note", text: stillLine }));
    return parts.length ? section("Still", ...parts) : null;
  }

  function fixedSection(view) {
    const slots = Array.isArray(view.slots) ? view.slots : [];
    return section("Fixed in the terminal",
      h("p", { class: "wb-steps-note wb-cr-note", text: `Face box: ${valueText(view.face_box)}` }),
      h("p", { class: "wb-steps-note wb-cr-note", text: `Cover: ${view.cover_offset_ms === null || view.cover_offset_ms === undefined ? "not set" : `${view.cover_offset_ms} ms`}` }),
      h("p", { class: "wb-steps-note wb-cr-note", text: `Theme: ${valueText(view.theme)}` }),
      ...slots.map((s) => h("p", { class: "wb-steps-note wb-cr-note", text: `Slot ${s.slot}: ${s.type}, beat ${s.beat}${s.description ? `, ${s.description}` : ""}` })),
      h("p", { class: "wb-steps-note wb-cr-note", text: TERMINAL_LINE }));
  }

  function footer() {
    const mode = modeNow();
    const foot = h("div", { class: "wb-cr-footer" });
    if (mode === "review" && may("answer") && may("video-run")) {
      foot.append(button("Continue: render the video", continueVideo, { extra: "pui-solid pui-theme", busyLabel: true }));
    }
    if (mode === "gate" && edited) {
      foot.append(h("p", { class: "wb-steps-note wb-cr-note", text: GATE_LINE }));
      if (may("video-run")) foot.append(button("Render again", renderAgain, { busyLabel: true }));
    }
    if (!canEdit(mode)) foot.append(h("p", { class: "wb-steps-note wb-cr-note", text: READ_ONLY_LINE }));
    foot.append(button("Close", close, { always: true, key: "close" }));
    return foot;
  }

  function draw() {
    refs.clear();
    const parts = [];
    if (loading && !data) {
      parts.push(h("p", { class: "wb-steps-note", role: "status", text: "Loading the captions..." }));
    } else if (!data) {
      parts.push(h("p", { class: "notice pui-soft pui-error wb-notice-card", role: "alert", text: readError || "The captions could not be read." }));
    } else {
      const view = data.view;
      parts.push(h("p", { class: "wb-cr-counts", text: countsText(view.counts) }));
      if (notice) parts.push(h("p", { class: "wb-steps-note wb-cr-notice", role: "status", text: notice }));
      if (failure) parts.push(h("p", { class: "notice pui-soft pui-error wb-notice-card", role: "alert", text: failure }));
      const still = stillSection();
      for (const piece of [still, wordsSection(view), retakesSection(view), beatsSection(view), animationsSection(view), fixedSection(view)]) if (piece) parts.push(piece);
    }
    if (!data) {
      if (notice) parts.push(h("p", { class: "wb-steps-note wb-cr-notice", role: "status", text: notice }));
    }
    parts.push(data ? footer() : h("div", { class: "wb-cr-footer" }, button("Close", close, { always: true, key: "close" })));
    body.replaceChildren(...parts);
    const target = refs.get(focusKey);
    focusKey = "";
    if (target && typeof target.focus === "function") target.focus();
  }

  return {
    el,
    /** Open the review of the video whose task is `task`, in `mode` ("review", "gate" or null); the service's own mode wins. */
    async open(openTask, mode) {
      cleanup();
      control = typeof AbortController === "function" ? new AbortController() : null;
      task = openTask;
      argMode = mode === undefined ? null : mode;
      data = null;
      readError = "";
      sel = null;
      fieldText = null;
      edited = false;
      notice = "";
      failure = "";
      stillLine = "";
      catalogue = null;
      catalogueOpen = false;
      addFor = null;
      typed = {};
      formProblem = "";
      loading = true;
      draw();
      if (!el.open && typeof el.showModal === "function") el.showModal();
      await read(false);
    },
  };
}
