// The caption review: "Check the captions" (amendment A4 of the short-video plan; runtime/captions.py and runtime/ops_pipeline.py are the other half). In the opened
// row of the code task of a recording (key media:<recording id>) the person reads the transcript as caption chunks, edits, splits, merges and deletes WORDS (the
// spelling stays as spoken), confirms or undoes each retake the code proposed, sees which words had their timing adjusted and which have no place, sees each beat of
// the script with its matched words and score (a beat below the threshold is flagged), anchors a beat to the words they select or drops its overlay, gives an empty
// asset slot a file or a choice, says where the face is and where the cover is taken, and presses Done. After Done the pipeline's steps are shown until the video card
// (floor/video-card.js) has something to show.
//
// Every change goes through one call, `captionsEdit`, with the revision the person last read and a list of the closed edit objects of captions-model.js: none of them has
// a field for a time. A refused change shows its reason as a sentence and changes nothing on screen (the same words, the same selection, the same typed text); the
// answer of an accepted one is the whole review again, which is what the page then shows. Done sends the revision and nothing else: no text leaves in it. The page never
// builds an image, fetches a model, changes the `media` settings or accepts a configuration; the picture of the face box and of the cover is a schematic of the frame
// (no still frame is made or shown here), and what was chosen is said in words and pixels. Every value from the service is put in with textContent (h()).
//
// The review is read and written on the Mac that runs the service: its routes answer on the loopback socket only, so on a page opened from a phone or over --lan the view
// says so and reads nothing but the pipeline's steps. The view is drawn in parts, each only when what it shows changed, so a read that changed nothing keeps what is typed
// and the focus.
//
//   env = {project, recording, api: {captionsRead, captionsEdit, captionsDone, prepareAgain, mediaList, uploadMedia, pollJob},
//          can(op) (optional: whether the page may do an operation, js/permissions.js), loopback (optional, default onLoopback()), changed() (optional: told when the pipeline moved,
//          so that the video card reads again), pollEvery (ms between asks for a running job, default 1500)}
// Returns {el, load({quiet}), close(), snapshot()}.

import { fill, h, svg } from "../dom.js";
import { reader } from "../permissions.js";
import { handOverStep } from "./hand-file.js";
import { mediaRefusal, onLoopback, uploadRecording } from "./media-upload.js";
import * as model from "./captions-model.js";
import { busyLine, chip, notice, withheldLine } from "./widgets.js";

export const ON_THE_MAC = "Check the captions on the Mac that runs the service: your words are read and changed there, and are not sent over the network.";
export const EDIT_HINT = `Keep the spelling as it is said. A space splits a word: its time is shared out and marked estimated. At most ${model.WORD_CHARS_MAX} characters.`;
export const DONE_WORDS = "Done says the captions are right and sends nothing of your words: the video is made from them on this Mac.";
export const FRAME_WORDS = "A schematic of the frame, not a picture: tap where the face is. The renderer draws the captions and overlays away from it.";
export const COVER_WORDS = "The cover is the frame of the finished video at the second you give; no picture is shown before the video is made.";
export const IMAGE_TYPES = "image/png,image/jpeg";

export function createCaptionsView(env) {
  const el = h("section", { class: "pui-card wb-card wb-rev", "aria-label": "Check the captions", "data-key": "captions-view" });
  const can = reader(env);
  const loopback = typeof env.loopback === "boolean" ? env.loopback : onLoopback();
  const api = env.api;
  const state = {
    view: null, media: null, mode: "loading", loading: true, error: null, message: null, job: false,
    selection: null, typed: { key: "", word: "", merge: "" }, busy: null, picked: {}, uploading: {}, uploadError: {},
    face: { size: "medium", fields: { x: "", y: "", w: "", h: "" } }, coverText: "",
  };
  let closed = false;
  let controller = null;
  const closing = new AbortController();      // aborted when the view closes: what is waiting (a job, a write) stops and says nothing

  const editing = () => state.mode === "review" && loopback && can("captions-edit");

  // --- reading ---------------------------------------------------------------------------------------------------------------------

  /** The recording as `media-list` knows it: where the pipeline stands and the ids of its asset slots. Never a refusal that stops the view. */
  async function readMedia() {
    try {
      const found = await api.mediaList(env.project, { recording: env.recording, signal: controller && controller.signal });
      state.media = (found.recordings || [])[0] || null;
    } catch (e) {
      if (e && e.name === "AbortError") throw e;
      state.media = state.media || null;
    }
  }

  async function load({ quiet = false } = {}) {
    if (closed) return;
    if (controller) controller.abort();
    controller = new AbortController();
    const mine = controller;
    if (!quiet && !state.view) {
      state.loading = true;
      draw();
    }
    try {
      if (!loopback) {
        await readMedia();
        state.mode = "mac";
      } else {
        const [view] = await Promise.all([api.captionsRead(env.project, env.recording, { signal: mine.signal }).catch((e) => e), readMedia()]);
        if (mine.signal.aborted) return;
        if (view instanceof Error || (view && view.name === "ApiError")) {
          if (view.name === "ApiError" && view.status === 409 && /not ready/.test(view.message || "")) {
            state.view = null;
            state.mode = "progress";
          } else {
            throw view;
          }
        } else {
          if (state.view && state.view.revision !== view.revision) {      // the words moved under the person: a selection or typed text would land on another word
            state.selection = null;
            state.typed = { key: "", word: "", merge: "" };
          }
          state.view = view;
          state.mode = state.job ? "running" : (view.editable ? "review" : "after");
          state.selection = model.selectionWithin(state.selection, view.words.length);
        }
      }
    } catch (e) {
      if (mine.signal.aborted || (e && e.name === "AbortError")) return;
      state.error = model.reasonOf(e);
      state.mode = state.view ? state.mode : "error";
    }
    state.loading = false;
    if (!closed) draw();
  }

  // --- the writes --------------------------------------------------------------------------------------------------------------------

  /** One call of `captions-edit` with the revision on screen. A refusal shows its reason and changes nothing else. Resolves true when accepted. */
  async function send(edits, doneWords) {
    if (state.busy || !state.view || !editing()) return false;
    state.busy = "edit";
    state.message = null;
    setBusy();
    try {
      const answer = await api.captionsEdit(env.project, env.recording, { revision: state.view.revision, edits, signal: closing.signal });
      if (closed) return false;
      state.view = { ...state.view, ...answer };
      state.error = null;
      state.selection = null;      // an accepted change ends the selection: the next click starts a new one, so a click never stretches an old range by surprise
      state.message = doneWords || null;
      state.busy = null;
      draw();
      return true;
    } catch (e) {
      if (closed) return false;
      state.error = model.reasonOf(e);
      state.busy = null;
      draw();
      return false;
    }
  }

  /** What a pipeline job left, as an error to show: the job failed, or the pipeline stopped at a step (a closed code). Null when it went well. */
  function jobProblem(last) {
    if (last.state === "failed") return { text: (last.error && last.error.message) || "The pipeline stopped.", code: "", field: "" };
    if (last.result && last.result.ok === false && last.result.code) {
      return { text: model.failureText({ step: last.result.failed, code: last.result.code, field: last.result.field, next: last.result.next }), code: last.result.code, field: "" };
    }
    return null;
  }

  /** Done sends the revision and nothing of the words, so it needs `captions-done` and the review, not the right to edit. */
  async function done() {
    const view = state.view;
    if (state.busy || !view || state.mode !== "review" || !loopback || !can("captions-done") || model.doneBlock(view)) return;
    state.busy = "done";
    state.job = true;
    state.message = null;
    state.error = null;
    state.mode = "running";
    draw();
    try {
      const job = await api.captionsDone(env.project, env.recording, { revision: view.revision, signal: closing.signal });
      const every = env.pollEvery || 1500;
      const last = await api.pollJob(job.job, every, { signal: closing.signal, onUpdate: () => { readMedia().then(() => { if (!closed) draw(); }).catch(() => {}); } });
      state.error = jobProblem(last);
    } catch (e) {
      if (closed) return;
      state.error = model.reasonOf(e);
    }
    state.busy = null;
    state.job = false;
    await load({ quiet: true });
    if (!closed && env.changed) env.changed();
  }

  async function reopen() {
    if (state.busy || !can("prepare-again") || !loopback) return;
    state.busy = "reopen";
    state.error = null;
    draw();
    try {
      const job = await api.prepareAgain(env.project, env.recording, "review", { signal: closing.signal });
      const last = await api.pollJob(job.job, env.pollEvery || 1500, { signal: closing.signal });
      state.error = jobProblem(last);
    } catch (e) {
      if (closed) return;
      state.error = model.reasonOf(e);
    }
    state.busy = null;
    await load({ quiet: true });
    if (!closed && env.changed) env.changed();
  }

  /** A file chosen for an asset slot goes to the media store by the same route as a recording, bound to the slot's id; then the review is read again. */
  async function upload(slot) {
    const file = state.picked[slot.slot];
    const id = slotId(slot.slot);
    if (!file || state.uploading[slot.slot]) return;
    const refusal = id ? mediaRefusal(file, { loopback }) : "This slot has no id yet: read the captions again.";
    if (refusal) {
      state.uploadError[slot.slot] = refusal;
      draw();
      return;
    }
    state.uploading[slot.slot] = { sent: 0, total: file.size };
    state.uploadError[slot.slot] = "";
    draw();
    try {
      await uploadRecording(api, env.project, file, { recording: env.recording, slot: id, bar: { set(sent, total) { state.uploading[slot.slot] = { sent, total }; paintUpload(slot.slot); } } });
      delete state.picked[slot.slot];
    } catch (e) {
      state.uploadError[slot.slot] = model.reasonOf(e).text;
    }
    delete state.uploading[slot.slot];
    await load({ quiet: true });
  }

  function slotId(key) {
    const slots = (state.media && state.media.slots) || {};
    return Object.keys(slots).find((id) => slots[id] && slots[id].key === key) || null;
  }

  // --- drawing: small pieces -------------------------------------------------------------------------------------------------------

  /** A button that sends an edit; `data-idle` marks it to be disabled while a call is in flight. */
  function act(label, key, onClick, { primary = false, disabled = false, small = true } = {}) {
    const node = h("button", { class: `pui-btn ${primary ? "pui-solid pui-theme" : "pui-surface pui-outline"} wb-card-button wb-rev-button${small ? " wb-small-button" : ""}`, type: "button", "data-key": key, "data-idle": "", "data-locked": disabled ? "" : null, disabled, text: label });
    node.addEventListener("click", onClick);
    return node;
  }

  function setBusy() {
    if (!el.querySelectorAll) return;
    for (const node of el.querySelectorAll("[data-idle]")) {
      if (state.busy) node.setAttribute("disabled", "");
      else if (node.getAttribute("data-locked") === null) node.removeAttribute("disabled");
    }
  }

  function paintUpload(slotKey) {
    const row = el.querySelector ? el.querySelector(`progress[data-slot="${slotKey}"]`) : null;
    const u = state.uploading[slotKey];
    if (row && u) row.value = u.total > 0 ? Math.min(100, Math.floor((u.sent / u.total) * 100)) : 0;
  }

  function labelled(label, control) {
    return h("label", { class: "pui-field-group wb-field" }, h("span", { class: "wb-field-label", text: label }), control);
  }

  function textField(key, label, value, onInput) {
    const input = h("input", { class: "pui-input wb-rev-input", type: "text", "data-key": key, "aria-label": label, autocomplete: "off", spellcheck: "false" });
    input.value = value;
    input.addEventListener("input", () => onInput(input.value));
    return input;
  }

  // --- drawing: the parts -------------------------------------------------------------------------------------------------------------

  function wordNode(word) {
    const classes = ["wb-rev-word"];
    const selected = state.selection && word.index >= state.selection.from && word.index <= state.selection.to;
    if (selected) classes.push("is-selected");
    if (word.retake) classes.push(word.retake === "confirmed" ? "is-cut" : "is-retake");
    if (word.timing_adjusted) classes.push("is-adjusted");
    if (word.estimated) classes.push("is-estimated");
    if (word.edited) classes.push("is-edited");
    if (word.left_out) classes.push("is-left-out");
    const marks = model.marks(word);
    const name = `${word.text}${marks.length ? `, ${marks.join(", ")}` : ""}`;
    // a word that is only read carries its marks in words after it (a CSS rule shows `data-marks`), so that they are seen and not only in a tooltip
    if (!editing()) return h("span", { class: classes.join(" "), "data-index": String(word.index), "data-marks": marks.join(", ") || null, "aria-label": marks.length ? name : null, title: marks.join(", ") || null, text: word.text });
    const node = h("button", { class: classes.join(" "), type: "button", "data-index": String(word.index), "aria-pressed": selected ? "true" : "false", "aria-label": name, title: marks.join(", ") || null, text: word.text });
    node.addEventListener("click", (event) => {
      const next = model.selectionAfter(state.selection, word.index, Boolean(event && event.shiftKey));
      const problem = model.rangeProblem(model.outsideSet(state.view), next);
      if (problem) {      // a range over words that are drawn apart is refused with a sentence, and the selection stays as it was
        state.error = { text: problem, code: "mixed_range", field: "" };
        draw();
        return;
      }
      state.selection = next;
      draw();
    });
    return node;
  }

  function transcriptNode(view) {
    const groups = model.groups(view);
    return h("div", { class: "wb-rev-transcript", role: "group", "aria-label": "The transcript, in caption chunks" },
      groups.map((group) => h("div", { class: `wb-rev-chunk${group.chunk === null ? " is-outside" : ""}`, "data-chunk": group.chunk === null ? "outside" : String(group.chunk) },
        h("span", { class: "wb-rev-clock mono", text: group.chunk === null ? "Not in the captions" : model.clock(group.start) }),
        h("span", { class: "wb-rev-words" }, group.words.map(wordNode)))),
      h("p", { class: "wb-card-hint wb-rev-legend", text: "Dashed strike-through: a retake the code proposes cutting. Red double strike-through on a tint: a retake you confirmed, cut. Dotted underline: the code adjusted the timing. Slanted: the time is an estimate. Dashed: you changed it." }));
  }

  /** A delete of the selected words: one edit for each word, at most MAX_EDITS in a call; more is refused with a sentence and nothing is sent. */
  function removeWords(sel, words) {
    const edits = model.edit.remove(sel.from, sel.to);
    if (!edits) {
      state.error = { text: model.REASONS.too_many_edits, code: "too_many_edits", field: "" };
      draw();
      return;
    }
    send(edits, words);
  }

  function selectionNode(view) {
    const sel = state.selection;
    const key = sel ? `${sel.from}-${sel.to}` : "";
    if (state.typed.key !== key) state.typed = { key, word: sel && sel.from === sel.to ? view.words[sel.from].text : "", merge: "" };
    const line = h("p", { class: "wb-card-note wb-rev-selection", "data-key": "selection-line", text: model.selectionLine(view, sel) });
    if (!sel || !editing()) return [line];
    const clear = act("Clear the selection", "clear-selection", () => { state.selection = null; draw(); });
    const count = sel.to - sel.from + 1;
    if (count === 1) {
      const input = textField("word", "The word, as spoken", state.typed.word, (v) => { state.typed.word = v; });
      return [line,
        labelled("The word, as spoken", input),
        h("p", { class: "wb-card-hint", text: EDIT_HINT }),
        h("div", { class: "wb-card-actions" },
          act("Save the spelling", "save-word", () => send([model.edit.word(sel.from, state.typed.word)], "Saved the spelling."), { primary: true }),
          act("Split at the spaces", "split-word", () => {
            const parts = state.typed.word.split(/\s+/).filter(Boolean);
            if (parts.length < 2) { state.error = { text: "Type the parts of the word with a space between them, then split.", code: "", field: "" }; draw(); return; }
            send([model.edit.split(sel.from, parts)], "Split the word.");
          }),
          act("Delete the word", "delete-word", () => removeWords(sel, "Deleted the word.")), clear),
      ];
    }
    const input = textField("merge", "One word for the whole range (optional)", state.typed.merge, (v) => { state.typed.merge = v; });
    return [line,
      labelled("One word for the whole range (optional; else the words are joined)", input),
      h("div", { class: "wb-card-actions" },
        act("Merge into one word", "merge-words", () => send([model.edit.merge(sel.from, sel.to, state.typed.merge.trim())], "Merged the words."), { primary: true }),
        act(`Delete these ${count} words`, "delete-words", () => removeWords(sel, `Deleted ${count} words.`)), clear),
    ];
  }

  function retakesNode(view) {
    const rows = model.retakeRows(view);
    if (!rows.length) return h("p", { class: "wb-empty-line", text: "No retake was found." });
    return h("ul", { class: "wb-rev-list", "data-key": "retakes" }, rows.map((r) => h("li", { class: `wb-rev-row${r.confirmed ? " is-confirmed" : ""}`, "data-retake": r.id },
      h("p", { class: "wb-rev-struck", text: r.gone ? "(every word of this repeat was deleted)" : r.text }),
      h("p", { class: "wb-card-hint", text: [r.span, `${model.seconds(r.seconds)} dropped`, r.kind].filter(Boolean).join(" · ") }),
      chip(r.confirmed ? "cut" : "proposed", r.confirmed ? "pui-error pui-soft" : "pui-muted pui-outline"),
      editing() ? h("div", { class: "wb-card-actions" }, act(r.confirmed ? "Undo" : "Confirm the cut", `retake-${r.id}`, () => send([model.edit.retake(r.id, !r.confirmed)], r.confirmed ? "Kept the words." : "Will cut the repeat."))) : null)));
  }

  function beatsNode(view) {
    const rows = model.beatRows(view);
    if (!rows.length) return h("p", { class: "wb-empty-line", text: "The script has no beat with an overlay." });
    const sel = state.selection;
    return h("ul", { class: "wb-rev-list", "data-key": "beats" }, rows.map((b) => h("li", { class: `wb-rev-row${b.needsLook ? " is-flagged" : ""}${b.dropped ? " is-dropped" : ""}`, "data-beat": String(b.beat) },
      h("p", { class: "wb-rev-beat-head" }, h("strong", { text: `Beat ${b.beat}` }), h("span", { class: "mono", text: ` ${b.preset}` }), h("span", { class: "wb-card-hint", text: ` · score ${model.scoreText(b.score)}` })),
      h("p", { class: "wb-rev-matched", text: b.text ? `${b.text}` : "No words matched." }),
      b.span ? h("p", { class: "wb-card-hint", text: b.span }) : null,
      b.flags.length ? h("p", { class: "wb-rev-flags" }, b.flags.map((f) => chip(f, b.needsLook && !b.anchored ? "pui-warn pui-soft" : "pui-muted pui-soft"))) : null,
      editing() ? h("div", { class: "wb-card-actions" },
        act(sel ? `Anchor to ${sel.from === sel.to ? `word ${sel.from + 1}` : `words ${sel.from + 1} to ${sel.to + 1}`}` : "Anchor to the selected words", `anchor-${b.beat}`,
          () => send([model.edit.anchor(b.beat, sel.from, sel.to)], `Anchored beat ${b.beat}.`), { disabled: !sel }),
        b.anchored ? act("Clear the anchor", `clear-anchor-${b.beat}`, () => send([model.edit.clearAnchor(b.beat)], `Cleared the anchor of beat ${b.beat}.`)) : null,
        act(b.dropped ? "Keep the overlay" : "Drop the overlay", `overlay-${b.beat}`, () => send([model.edit.overlay(b.beat, !b.dropped)], b.dropped ? `Kept the overlay of beat ${b.beat}.` : `Dropped the overlay of beat ${b.beat}.`))) : null)));
  }

  function wordsNode(view) {
    const adjusted = view.words.filter((w) => w.timing_adjusted);
    const unplaced = view.unplaced || [];
    return [
      h("details", { class: "wb-rev-details", "data-key": "adjusted" },
        h("summary", { text: `Words whose timing was adjusted (${adjusted.length})` }),
        adjusted.length ? h("p", { class: "wb-rev-plain", text: adjusted.map((w) => w.text).join(" ") }) : h("p", { class: "wb-empty-line", text: "None." }),
        h("p", { class: "wb-card-hint", text: "The code moved these words into the sound they belong to; you did not change them." })),
      h("details", { class: "wb-rev-details", "data-key": "unplaced" },
        h("summary", { text: `Words with no place in the video (${unplaced.length})` }),
        unplaced.length ? h("ul", { class: "wb-rev-list" }, unplaced.map((u) => h("li", { class: "wb-rev-row", "data-unplaced": String(u.index) },
          h("span", { text: u.word === null || u.word === undefined ? "(deleted)" : view.words[u.word] ? view.words[u.word].text : "" }),
          h("span", { class: "wb-card-hint", text: ` · ${model.seconds(u.start)} to ${model.seconds(u.end)}` })))) : h("p", { class: "wb-empty-line", text: "None." }),
        h("p", { class: "wb-card-hint", text: "Left out of the captions: they sit in silence the transcriber could not place them in." })),
    ];
  }

  function slotsNode(view) {
    if (!view.slots.length) return h("p", { class: "wb-empty-line", text: "The script needs no file from you." });
    return h("ul", { class: "wb-rev-list", "data-key": "slots" }, view.slots.map((s) => {
      const picked = state.picked[s.slot];
      const sending = state.uploading[s.slot];
      const input = h("input", { class: "wb-file", type: "file", accept: s.type === "image" ? IMAGE_TYPES : null, "aria-label": `File for ${s.slot}`, tabindex: "-1", "data-slot": s.slot });
      input.addEventListener("change", () => {
        const file = input.files && input.files[0];
        state.picked[s.slot] = file || undefined;
        state.uploadError[s.slot] = "";
        draw();
      });
      const choose = h("button", { class: "pui-btn pui-surface pui-outline wb-small-button wb-hand-choose", type: "button", "data-key": `choose-${s.slot}`, "data-idle": "", text: s.file ? "Choose another file" : "Choose a file" });
      choose.addEventListener("click", () => { if (!input.disabled) input.click(); });
      const select = h("select", { class: "pui-input wb-rev-select", "data-key": `choice-${s.slot}`, "data-idle": "", "aria-label": `If ${s.slot} gets no file` },
        [["", "No choice yet"], ["keyword", "Use a keyword instead"], ["none", "Leave the overlay out"]].map(([value, label]) => h("option", { value, selected: (s.choice || "") === value, text: label })));
      select.value = s.choice || "";
      select.addEventListener("change", () => send([model.edit.slot(s.slot, select.value || null)], "Saved the choice for the slot."));
      const state_ = s.file ? (s.file.stale ? "A file is there, but the slot's description changed: upload again." : `File: ${s.file.name || "(no name)"} (${s.file.type || "?"})`) : "No file yet.";
      return h("li", { class: `wb-rev-row${!s.file && !s.choice ? " is-flagged" : ""}`, "data-slot-row": s.slot },
        h("p", { class: "wb-rev-beat-head" }, h("strong", { text: s.slot }), h("span", { class: "wb-card-hint", text: ` · beat ${s.beat}, ${s.param}, ${s.type}` })),
        h("p", { class: "wb-rev-matched", text: s.description }),
        h("p", { class: "wb-card-note", "data-key": `slot-state-${s.slot}`, text: state_ }),
        s.type === "clip" ? h("p", { class: "wb-card-hint", text: "The renderer takes a PNG or JPEG image for now." }) : null,
        editing() && can("media-in") ? h("div", { class: "wb-hand wb-rev-hand" },
          h("div", { class: "wb-hand-row" }, choose),
          input,
          handOverStep(picked, null, () => upload(s), { disabled: Boolean(sending), label: "Upload for this slot" }),
          sending ? h("progress", { class: "wb-media-progress", max: "100", value: "0", "data-slot": s.slot, "aria-label": "Upload progress" }) : null,
          state.uploadError[s.slot] ? h("p", { class: "wb-card-error", role: "alert", text: state.uploadError[s.slot] }) : null) : null,
        editing() && !can("media-in") ? h("p", { class: "wb-card-hint", "data-key": `upload-off-${s.slot}`, text: "Uploading a file is turned off for the page (media-in): choose below, or upload in the terminal." }) : null,
        // a slot with no file, or whose file went stale, can always be answered with a choice: neither an upload that is turned off nor a stale file blocks Done
        editing() && (!s.file || s.file.stale) ? labelled(s.file ? "Or, instead of a new file" : "Or, with no file", select) : null);
    }));
  }

  /** The recording's length in seconds when `media-list` gave it, else null. The cover is a frame of the finished video, which is no longer than the recording. */
  function recordingSeconds() {
    const found = state.media && state.media.raw ? Number(state.media.raw.duration) : NaN;
    return Number.isFinite(found) && found > 0 ? found : null;
  }

  /** A face box edit; what the person typed in the four numbers is dropped only when the service accepted it, so a refusal leaves their numbers to correct. */
  async function faceEdit(edit, words) {
    if (await send([edit], words)) {
      state.face.fields = { x: "", y: "", w: "", h: "" };
      draw();
    }
  }

  /** A cover edit; the typed seconds are dropped only when the service accepted it. */
  async function coverEdit(offsetMs, words) {
    if (await send([model.edit.cover(offsetMs)], words)) {
      state.coverText = "";
      draw();
    }
  }

  function frameNode(view) {
    const box = view.face_box;
    const frame = svg("svg", { class: "wb-rev-frame", viewBox: `0 0 ${model.FRAME.w} ${model.FRAME.h}`, role: "img", "aria-label": "The 9 by 16 frame: tap where the face is", "data-key": "frame" },
      svg("rect", { x: "0", y: "0", width: String(model.FRAME.w), height: String(model.FRAME.h), class: "wb-rev-frame-bg" }),
      box ? svg("rect", { x: String(box.x), y: String(box.y), width: String(box.w), height: String(box.h), class: "wb-rev-facebox", "data-key": "facebox" }) : null);
    if (editing()) {
      frame.addEventListener("click", (event) => {
        const rect = frame.getBoundingClientRect ? frame.getBoundingClientRect() : null;
        if (!rect || !rect.width || !rect.height || !event) return;
        const next = model.faceBoxAt((event.clientX - rect.left) / rect.width, (event.clientY - rect.top) / rect.height, model.FACE_SIZES[state.face.size]);
        faceEdit(model.edit.faceBox(next), "Chose the face box.");
      });
    }
    const f0 = state.face.fields;
    const fields = ["x", "y", "w", "h"].map((k) => {
      const input = h("input", { class: "pui-input wb-rev-number", type: "text", inputmode: "numeric", "data-key": `face-${k}`, "aria-label": `Face box ${k}, in pixels`, autocomplete: "off" });
      input.value = f0[k] !== "" ? f0[k] : box ? String(box[k]) : "";
      input.addEventListener("input", () => { state.face.fields[k] = input.value; });
      return labelled(k, input);
    });
    const cover = textField("cover", "Cover: seconds into the finished video", state.coverText !== "" ? state.coverText : (view.cover_offset_ms / 1000).toFixed(1), (v) => { state.coverText = v; });
    return h("div", { class: "wb-rev-frame-box" },
      h("p", { class: "wb-card-hint", text: FRAME_WORDS }),
      frame,
      h("p", { class: "wb-card-note", "data-key": "face-line", text: model.faceBoxText(box) }),
      editing() ? [
        h("div", { class: "wb-rev-sizes", role: "group", "aria-label": "Size of the face box" }, Object.keys(model.FACE_SIZES).map((name) => {
          const node = act(name, `size-${name}`, () => { state.face.size = name; draw(); }, { primary: state.face.size === name });
          node.setAttribute("aria-pressed", state.face.size === name ? "true" : "false");
          return node;
        })),
        h("div", { class: "wb-rev-numbers" }, fields),
        h("div", { class: "wb-card-actions" },
          act("Set the face box", "set-face", () => {
            const f = state.face.fields;      // read now: the object is replaced when a face box edit was accepted
            const got = model.faceBoxFromFields({ x: f.x !== "" ? f.x : box ? box.x : "", y: f.y !== "" ? f.y : box ? box.y : "", w: f.w !== "" ? f.w : box ? box.w : "", h: f.h !== "" ? f.h : box ? box.h : "" });
            if (got.reason) { state.error = { text: got.reason, code: "", field: "" }; draw(); return; }
            faceEdit(model.edit.faceBox(got.box), "Chose the face box.");
          }),
          box ? act("Clear the face box", "clear-face", () => faceEdit(model.edit.clearFaceBox(), "Cleared the face box.")) : null),
        labelled("Cover: seconds into the finished video", cover),
        h("div", { class: "wb-card-actions" }, act("Set the cover", "set-cover", () => {
          const got = model.coverFromSeconds(state.coverText !== "" ? state.coverText : String(view.cover_offset_ms / 1000), recordingSeconds());
          if (got.reason) { state.error = { text: got.reason, code: "", field: "" }; draw(); return; }
          coverEdit(got.offsetMs, "Chose the cover.");
        }), act("First frame", "cover-first", () => coverEdit(0, "The cover is the first frame."))),
      ] : null,
      h("p", { class: "wb-card-note", "data-key": "cover-line", text: model.coverText(view.cover_offset_ms) }),
      h("p", { class: "wb-card-hint", text: COVER_WORDS }));
  }

  function stepsNode() {
    const steps = (state.media && state.media.pipeline && state.media.pipeline.steps) || (state.view && state.view.steps) || null;
    const failure = (state.media && state.media.pipeline && state.media.pipeline.failure) || (state.view && state.view.failure) || null;
    if (!steps) return h("p", { class: "wb-empty-line", text: "The pipeline has not started for this recording." });
    return [
      h("ol", { class: "wb-rev-steps", "data-key": "steps" }, model.stepRows(steps).map((r) => h("li", { class: `wb-rev-step is-${r.status}`, "data-step": r.step }, h("span", { text: r.label }), h("span", { class: "wb-card-hint", text: ` — ${r.word}` })))),
      failure ? notice(model.failureText(failure), "error", h("code", { class: "mono wb-rev-code", text: ` ${failure.code}` })) : null,
    ];
  }

  function doneNode(view) {
    if (state.mode === "review" && view) {
      const block = model.doneBlock(view);
      return h("div", { class: "wb-rev-done" },
        block ? h("p", { class: "wb-card-note", "data-key": "done-block", role: "status", text: block }) : null,
        loopback && can("captions-done") ? h("div", { class: "wb-card-actions" }, act("Done: the captions are right", "done", done, { primary: true, small: false, disabled: Boolean(block) })) : null,
        h("p", { class: "wb-card-hint", text: DONE_WORDS }));
    }
    if (state.mode === "after" && loopback && can("prepare-again")) {
      return h("div", { class: "wb-card-actions" }, act("Open the captions again", "reopen", reopen));
    }
    return null;
  }

  // --- drawing: the skeleton and the parts ---------------------------------------------------------------------------------------------

  const PART_NAMES = ["notes", "summary", "steps", "transcript", "selection", "retakes", "beats", "words", "slots", "frame", "done", "actions", "withheld"];
  const parts = {};
  let shape = null;

  function skeleton() {
    parts.head = { node: h("div", { class: "wb-card-head wb-rev-head" }), sig: null };
    for (const name of PART_NAMES) parts[name] = { node: h("div", { class: "wb-rev-part", "data-part": name }), sig: null };
    fill(el, parts.head.node, h("div", { class: "wb-card-content wb-rev-content" }, PART_NAMES.map((n) => parts[n].node)));
    shape = "parts";
  }

  function paint(name, signature, produce) {
    const part = parts[name];
    const key = JSON.stringify(signature);
    if (part.sig === key) return;
    part.sig = key;
    fill(part.node, [produce()].flat(Infinity));
  }

  function section(title, body) {
    return h("section", { class: "wb-rev-section" }, h("h4", { class: "wb-rev-heading", text: title }), body);
  }

  function noteNodes() {
    const view = state.view;
    return [
      state.mode === "mac" ? notice(ON_THE_MAC, "warn") : null,
      state.error ? notice(`${state.error.text}`, "error", state.error.code ? h("code", { class: "mono wb-rev-code", text: ` ${state.error.code}${state.error.field ? ` ${state.error.field}` : ""}` }) : null,
        state.error.code === "stale_revision" ? act("Read the captions again", "reread", () => { state.error = null; load({ quiet: true }); }) : null) : null,
      state.message ? h("p", { class: "wb-card-note", role: "status", "data-key": "message", text: state.message }) : null,
      view && view.sent_back ? h("div", { class: "wb-rev-sentback", "data-key": "sent-back", role: "note" },
        h("strong", { text: "The video was sent back for review" }), h("p", { class: "wb-rev-plain", text: view.sent_back.comment || "" }), h("p", { class: "wb-card-hint", text: view.sent_back.at || "" })) : null,
    ];
  }

  function draw() {
    if (closed) return;
    if (state.mode === "loading" && state.loading) {
      shape = null;
      fill(el, h("div", { class: "wb-card-content" }, busyLine("Loading the captions...")));
      return;
    }
    if (state.mode === "error") {
      shape = null;
      fill(el, h("div", { class: "wb-card-content" }, notice(state.error ? state.error.text : "The captions could not be read.", "error"), h("div", { class: "wb-card-actions" }, act("Try again", "reload", () => load()))));
      return;
    }
    if (shape !== "parts") skeleton();
    const view = state.view;
    const mode = state.mode;
    const withheld = [];
    for (const op of ["captions-edit", "captions-done", "prepare-again", "media-in"]) if (!can(op)) withheld.push(op);
    const stateWord = { review: ["Waiting for you", "pui-muted pui-soft"], after: ["Checked", "pui-theme pui-soft"], running: ["Running", "pui-muted pui-soft"], progress: ["Not at the review yet", "pui-muted pui-soft"], mac: ["On the Mac", "pui-warn pui-soft"] }[mode] || ["", ""];
    paint("head", [mode], () => [h("strong", { class: "wb-card-title", text: "Check the captions" }), chip(stateWord[0], stateWord[1])]);
    paint("notes", [mode, state.error, state.message, view && view.sent_back], noteNodes);
    paint("summary", [view && view.counts, mode], () => (view && (mode === "review" || mode === "after") ? h("p", { class: "wb-card-hint wb-rev-counts", "data-key": "counts", text: countsLine(view.counts) }) : null));
    paint("steps", [mode, state.media && state.media.pipeline, view && view.steps, view && view.failure], () => (mode === "review" ? null : section("Where the pipeline stands", stepsNode())));
    const open = view && (mode === "review" || mode === "after");
    paint("transcript", [open && view.words, open && view.chunks, open && view.retakes, mode, can("captions-edit"), state.selection], () => (open ? section("The words", [transcriptNode(view)]) : null));
    paint("selection", [mode === "review" && state.selection, mode === "review" && view && state.selection ? view.words.slice(state.selection.from, state.selection.to + 1).map((w) => w.text) : null, can("captions-edit")], () => (mode === "review" && view ? selectionNode(view) : null));
    paint("retakes", [mode, open && view.retakes, open && view.words.length, can("captions-edit")], () => (open ? section("Retakes", retakesNode(view)) : null));
    paint("beats", [mode, open && view.beats, open && view.threshold, state.selection, open && view.words.length, can("captions-edit")], () => (open ? section(`Beats of the script${Number.isFinite(view.threshold) ? ` (a match below ${view.threshold} is flagged)` : ""}`, beatsNode(view)) : null));
    paint("words", [open && view.words.filter((w) => w.timing_adjusted).map((w) => w.index), open && view.unplaced, open && view.words.length], () => (open ? wordsNode(view) : null));
    paint("slots", [mode, open && view.slots, open && state.media && state.media.slots, Object.keys(state.picked).map((k) => [k, state.picked[k] && state.picked[k].name]), state.uploading, state.uploadError, can("captions-edit"), can("media-in")], () => (open ? section("Asset slots", slotsNode(view)) : null));
    paint("frame", [mode, open && view.face_box, open && view.cover_offset_ms, state.face, state.coverText, can("captions-edit")], () => (open ? section("Face box and cover", frameNode(view)) : null));
    paint("done", [mode, open && view && model.doneBlock(view), can("captions-done"), can("prepare-again")], () => doneNode(view));
    paint("actions", [mode], () => h("div", { class: "wb-card-actions" }, act("Check again", "reload", () => { state.error = null; state.message = null; load({ quiet: true }); })));
    paint("withheld", [withheld], () => withheldLine(withheld));
    setBusy();
  }

  function countsLine(c) {
    return [`${c.words} words`, c.edited ? `${c.edited} changed by you` : null, c.timing_adjusted ? `${c.timing_adjusted} with adjusted timing` : null, c.estimated ? `${c.estimated} with estimated timing` : null,
      c.unplaced ? `${c.unplaced} with no place` : null, `${c.confirmed} of ${c.retakes} retakes cut`, `${c.beats} beats${c.below_threshold ? `, ${c.below_threshold} to look at` : ""}`].filter(Boolean).join(" · ");
  }

  return {
    el,
    load,
    /** The row closed or the task went away: stop what is going. */
    close() {
      closed = true;
      closing.abort();
      if (controller) controller.abort();
    },
    /** For a test: what the last draw was made from. */
    snapshot() {
      return { mode: state.mode, selection: state.selection && { ...state.selection }, view: state.view, busy: state.busy };
    },
  };
}
