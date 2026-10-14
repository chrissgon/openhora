// The caption review's pure side (interface/js/floor/captions-view.js draws it; runtime/captions.py and runtime/ops_pipeline.py are the other half): the
// words a refusal is told in, the rows the view builds from `captions-read`, the selection of words, and the closed edit objects `captions-edit` takes. No DOM
// and no network here. The page changes WORDS and decisions, never a time: there is no builder in this file that carries one, and the face box and the cover's
// offset are the two numbers the review stores (the cover's offset is the position of a still frame, not a time the captions use).

export const FRAME = Object.freeze({ w: 1080, h: 1920 });       // runtime/captions.py FRAME: the output frame the face box is given in
export const COVER_MAX_MS = 600000;                              // runtime/captions.py COVER_MAX_MS
export const WORD_CHARS_MAX = 40;                                // runtime/captions.py WORD_CHARS_MAX, shown in the hint; the service checks it

/** The closed refusals of runtime/captions.py and runtime/ops_pipeline.py, each in a sentence for the person. A code that is not here is shown as it came. */
export const REASONS = Object.freeze({
  stale_revision: "The captions changed since you read them (another tab, or another edit). Read them again, then make the change again.",
  time_not_accepted: "A time cannot be given: you change words, the times are code's.",
  bad_edit: "That edit is not one the captions take.",
  unknown_edit: "That kind of edit is not one the captions take.",
  unknown_field: "That edit carries a field it does not take.",
  bad_index: "A word of that edit is not in the captions any more.",
  overlapping_edits: "Two of the changes touch the same word.",
  merge_across_segments: "Words from two different segments cannot be merged: select words that are said together.",
  not_text: "That is not text.",
  forbidden_character: "A word cannot hold a control or invisible character.",
  empty_text: "A word cannot be empty.",
  text_too_long: `A word is at most ${WORD_CHARS_MAX} characters.`,
  unknown_retake: "That retake is not one of the proposals.",
  unknown_beat: "That beat has no overlay to change.",
  unknown_slot: "That asset slot is not in the script.",
  bad_choice: "That choice is not one an empty slot takes.",
  bad_face_box: "The face box must be inside the frame and have a size.",
  bad_cover: "The cover's position must be inside the recording.",
  no_words: "At least one word has to stay in the captions.",
  too_many_words: "That would make more words than a video takes.",
  credential_in_transcript: "A word looks like a key or a password: it is not kept.",
  slot_needs_a_choice: "An asset slot has no file and no choice: give it a file, or choose to use a keyword or nothing.",
  space_in_word: "A word cannot hold a space: split it into words, or give the merge a single word.",
  review_disagrees: "The edited words and your decisions no longer agree (a write was cut short): open the captions again.",
  review_unreadable: "The review's file cannot be read: open the captions again.",
  edited_unreadable: "The edited words cannot be read: open the captions again.",
});

/**
 * The closed codes a pipeline step stops with (runtime/pipeline.py `StepFailure`, and the words the transcriber's and the renderer's own refusals are reduced to), each in a
 * sentence. The command to run, when there is one, comes from the service (`next`) and is shown beside the sentence.
 */
export const FAILURE_WORDS = Object.freeze({
  file_unreadable: "A file of this recording could not be read.",
  file_missing: "A file the step needs is missing.",
  post_unreadable: "The post file could not be read: check its path under docs/.",
  unknown_step: "That step is not one the pipeline has.",
  transcript_invalid: "The transcriber's answer is not a transcript the pipeline can use.",
  slots_frozen: "The asset slots are frozen: an effect is open for this recording.",
  slot_empty: "An asset slot has no file: give it one, or choose a keyword or nothing.",
  script_refused: "The post file's script was refused by its own checker: fix the post file, then open the captions again.",
  retake_lost: "A retake you confirmed no longer matches a repeat after your edits. Open the captions again and confirm it again.",
  anchor_lost: "A beat you anchored lost its words after your edits: anchor it again.",
  render_not_verified: "The rendered file did not pass the check against the platform's rules, so it was not kept.",
  render_missing: "The render finished but its file is not there.",
  render_cap: "The store already holds as many renders as it may: remove one first.",
  cover_missing: "The cover frame could not be cut.",
  asset_type: "An asset must be a PNG or JPEG image for now.",
  recording_changed: "The recording changed since the pipeline began: start over from the first step.",
  provider_output_invalid: "A provider answered with something the pipeline cannot read as a result. Run the step again.",
  not_configured: "The media settings (model and language) are not set: set them in runtime.json, then accept the configuration in the terminal.",
  no_recording: "The recording's file is missing.",
  io_error: "A file could not be written (a full disk?).",
  credential_in_transcript: "A word looks like a key or a password: it is not kept.",
  docker_missing: "Docker is not installed.",
  docker_not_answering: "Docker is not answering: start it.",
  docker_daemon_not_local: "Docker is not a local daemon: the pipeline only uses a local one.",
  docker_unusable: "Docker cannot be used here.",
  image_not_built: "The provider's image is not built: build it with your own terminal command.",
  image_stale: "The provider's image is out of date: build it again with your own terminal command.",
  image_not_recorded: "The provider's image has no record: build it with your own terminal command.",
  model_missing: "The speech model is not on this Mac: see the command to fetch it in your own terminal.",
  model_mismatch: "The speech model on this Mac is not the one pinned.",
  pin_incomplete: "The browser's pin is incomplete: complete it with your own terminal command.",
  folder_unusable: "A folder of the store is not private to you.",
  timeout: "A step took longer than its limit.",
  usage: "A step was given something it does not take.",
  failed: "A step failed.",
  cancelled: "The request was cancelled: the pipeline of this recording stopped with it.",
  busy: "The pipeline of this recording is being run by another process: wait for it to end.",
});

/** A step's failure as one sentence for the person: the sentence of its closed code (else the code), the field in brackets, then the command to run when the service gave one. */
export function failureText(failure) {
  if (!failure) return "";
  const code = String(failure.code || "failed");
  const field = failure.field ? ` (${failure.field})` : "";
  const sentence = FAILURE_WORDS[code] || REASONS[code] || code;
  const step = failure.step ? `${STEP_WORDS[failure.step] || failure.step} stopped: ` : "A step stopped: ";
  return `${step}${sentence}${field}${failure.next ? ` Run: ${failure.next}` : ""}`;
}

/** The reason a refused call is shown with: the sentence for its closed code, with the field in small words, else the service's own message. */
export function reasonOf(error) {
  const message = error && typeof error.message === "string" ? error.message : "";
  const found = /refused: ([a-z_]+)(?: ([A-Za-z0-9_.\[\]]+))?/.exec(message);
  if (found && REASONS[found[1]]) return { text: REASONS[found[1]], code: found[1], field: found[2] || "" };
  if (/already being run/.test(message)) return { text: FAILURE_WORDS.busy, code: "busy", field: "" };
  const closed = /^([a-z_]+)(?: ([A-Za-z0-9_.\[\]-]{1,40}))?(?: -- (.*))?$/.exec(message);      // a refusal of the pipeline itself: "<code> <field> -- <command>"
  if (closed && FAILURE_WORDS[closed[1]]) return { text: FAILURE_WORDS[closed[1]] + (closed[3] ? ` Run: ${closed[3]}` : ""), code: closed[1], field: closed[2] || "" };
  if (error && error.name === "ApiError" && error.status === 0) return { text: "The service could not be reached. Is it still running?", code: "network", field: "" };
  if (error && error.name === "ApiError" && error.status === 404) return { text: "This recording's captions are not here (the service answers them on the Mac that runs it).", code: "not_found", field: "" };
  return { text: message || "The request failed.", code: "", field: "" };
}

/** "12.3 s", from seconds; "" for a value that is not a time. */
export function seconds(value) {
  return Number.isFinite(value) ? `${Number(value).toFixed(1)} s` : "";
}

/** "0:12": the clock a chunk starts at. */
export function clock(value) {
  if (!Number.isFinite(value) || value < 0) return "";
  const whole = Math.floor(value);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/** The words `from` to `to` (inclusive) of a view as one line of text, at most `limit` words, then an ellipsis. */
export function textOf(words, from, to, limit = 10) {
  if (!Array.isArray(words) || !Number.isInteger(from) || !Number.isInteger(to) || from > to) return "";
  const chosen = words.slice(from, to + 1).map((w) => w.text);
  return chosen.length > limit ? `${chosen.slice(0, limit).join(" ")} …` : chosen.join(" ");
}

/** The time span of words `from` to `to`: "12.3 s to 15.0 s", or "" when either is unknown. Read-only: the review never writes a time. */
export function spanText(words, from, to) {
  if (!Array.isArray(words) || !Number.isInteger(from) || !Number.isInteger(to) || !words[from] || !words[to]) return "";
  return `${seconds(words[from].start)} to ${seconds(words[to].end)}`;
}

/**
 * The groups the transcript is drawn in: one for each caption chunk, in order, each {chunk, start, words: [row]}, then the words that are in no chunk (left out
 * of the captions) as one group with chunk null. The rows are the view's, with `retake` ("proposed" | "confirmed" | null) from the retakes that cover them.
 */
export function groups(view) {
  const words = (view && view.words) || [];
  const retake = new Array(words.length).fill(null);
  for (const r of (view && view.retakes) || []) {
    if (!Number.isInteger(r.word_from) || !Number.isInteger(r.word_to)) continue;
    for (let i = r.word_from; i <= r.word_to && i < words.length; i += 1) retake[i] = r.confirmed ? "confirmed" : (retake[i] || "proposed");
  }
  const row = (i) => ({ ...words[i], retake: retake[i] });
  const out = [];
  const placed = new Set();
  for (const chunk of (view && view.chunks) || []) {
    const rows = chunk.words.filter((i) => words[i]).map((i) => { placed.add(i); return row(i); });
    if (rows.length) out.push({ chunk: chunk.chunk, start: rows[0].start, words: rows });
  }
  const rest = words.filter((w) => !placed.has(w.index)).map((w) => row(w.index));
  if (rest.length) out.push({ chunk: null, start: rest[0].start, words: rest });
  return out;
}

/** The marks a word shows, as short phrases, in a fixed order (also what its accessible name says). */
export function marks(word) {
  const out = [];
  if (word.retake === "confirmed") out.push("retake, cut");
  else if (word.retake === "proposed") out.push("retake proposed");
  if (word.timing_adjusted) out.push("timing adjusted");
  if (word.estimated) out.push("timing estimated");
  if (word.edited) out.push("edited");
  if (word.left_out === "unplaced") out.push("no place in the video");
  else if (word.left_out === "dropped_segment") out.push("left out");
  return out;
}

/** The retakes as rows: the words they would drop (struck through), the span in the recording, how long, and whether the person confirmed it. */
export function retakeRows(view) {
  const words = (view && view.words) || [];
  return ((view && view.retakes) || []).map((r) => ({
    id: r.id, kind: r.kind, confirmed: r.confirmed, seconds: r.seconds, gone: !Number.isInteger(r.word_from),
    text: textOf(words, r.word_from, r.word_to), span: spanText(words, r.word_from, r.word_to), from: r.word_from, to: r.word_to,
  }));
}

/** The beats as rows, each with the words it matched (text and span), and the one flag it needs shown, in words. */
export function beatRows(view) {
  const words = (view && view.words) || [];
  const threshold = view && view.threshold;
  return ((view && view.beats) || []).map((b) => {
    const flags = [];
    if (b.dropped) flags.push("overlay dropped");
    if (b.anchored) flags.push("anchored by you");
    else if (!b.matched) flags.push("no match in the words");
    else if (b.below_threshold) flags.push(`below the threshold${Number.isFinite(threshold) ? ` (${threshold})` : ""}`);
    if (b.reordered) flags.push("said in another order");
    if (b.fallback) flags.push("shown as another preset");
    return { beat: b.beat, preset: b.preset, score: b.score, matched: b.matched, anchored: b.anchored, dropped: b.dropped, below: Boolean(b.below_threshold),
      flags, text: textOf(words, b.word_from, b.word_to), span: spanText(words, b.word_from, b.word_to), from: b.word_from, to: b.word_to, needsLook: !b.dropped && (!b.matched || b.below_threshold) };
  });
}

/** The score as the person reads it: "0.72", or "none". */
export function scoreText(score) {
  return Number.isFinite(score) ? Number(score).toFixed(2) : "none";
}

// --- the selection of words ---------------------------------------------------------------------------------------------------------

/**
 * The selection after a click on word `index`: the first click selects it; a click on another word while one word is selected (or with `extend`, the shift key)
 * extends the selection to the range between them; a click on a word of a range, or on the single selected word, clears it; a click while a range is selected
 * starts a new selection at that word. {from, to} or null.
 */
export function selectionAfter(selection, index, extend = false) {
  if (!Number.isInteger(index) || index < 0) return selection || null;
  if (!selection) return { from: index, to: index };
  if (extend || selection.from === selection.to) {
    if (selection.from === selection.to && selection.from === index) return null;
    return { from: Math.min(selection.from, index), to: Math.max(selection.from, index) };
  }
  if (index >= selection.from && index <= selection.to) return null;
  return { from: index, to: index };
}

/** The selection kept inside the words of a view after the words changed (an edit moved the numbering): null when it no longer names words. */
export function selectionWithin(selection, count) {
  if (!selection || selection.from >= count) return null;
  return { from: selection.from, to: Math.min(selection.to, count - 1) };
}

/** The sentence under the transcript for the selection. */
export function selectionLine(view, selection) {
  if (!selection) return "Select a word to change it; select a second word to take the words between them.";
  const count = selection.to - selection.from + 1;
  const where = count === 1 ? `Word ${selection.from + 1}` : `Words ${selection.from + 1} to ${selection.to + 1}`;
  return `${where} selected: ${textOf(view.words, selection.from, selection.to, 8)}`;
}

// --- the closed edit objects of `captions-edit` --------------------------------------------------------------------------------------------

export const edit = Object.freeze({
  word: (index, text) => ({ op: "edit", index, text }),
  split: (index, parts) => ({ op: "split", index, parts }),
  merge: (from, to, text) => (text ? { op: "merge", from, to, text } : { op: "merge", from, to }),
  remove: (from, to) => Array.from({ length: to - from + 1 }, (_, k) => ({ op: "delete", index: from + k })),
  retake: (id, confirmed) => ({ op: "retake", id, confirmed }),
  anchor: (beat, from, to) => ({ op: "anchor", beat, word_from: from, word_to: to }),
  clearAnchor: (beat) => ({ op: "anchor", beat, clear: true }),
  overlay: (beat, dropped) => ({ op: "overlay", beat, dropped }),
  slot: (slot, choice) => ({ op: "slot", slot, choice }),
  faceBox: (box) => ({ op: "face_box", x: box.x, y: box.y, w: box.w, h: box.h }),
  clearFaceBox: () => ({ op: "face_box", clear: true }),
  cover: (offsetMs) => ({ op: "cover", offset_ms: offsetMs }),
});

/** The keys an edit object may carry, by kind: the same closed lists as runtime/captions.py OPS (a test ties them). No key of any names a time. */
export const EDIT_KEYS = Object.freeze({
  edit: ["index", "text"], delete: ["index"], merge: ["from", "to", "text"], split: ["index", "parts"], retake: ["id", "confirmed"],
  anchor: ["beat", "word_from", "word_to", "clear"], overlay: ["beat", "dropped"], slot: ["slot", "choice"], face_box: ["x", "y", "w", "h", "clear"], cover: ["offset_ms"],
});

// --- the face box and the cover ----------------------------------------------------------------------------------------------------------

export const FACE_SIZES = Object.freeze({ small: 280, medium: 420, large: 600 });      // the box's side in frame pixels, chosen by words

/** A face box of `size` frame pixels centred where the person tapped on the frame (a fraction 0 to 1 of its width and height), kept inside the frame. */
export function faceBoxAt(fx, fy, size) {
  const side = Math.min(Math.round(size), FRAME.w);
  const x = Math.min(Math.max(Math.round(fx * FRAME.w - side / 2), 0), FRAME.w - side);
  const y = Math.min(Math.max(Math.round(fy * FRAME.h - side / 2), 0), FRAME.h - side);
  return { x, y, w: side, h: side };
}

/** The face box as the page says it: what was chosen, in pixels of the output frame. */
export function faceBoxText(box) {
  return box ? `Face box: ${box.w} × ${box.h} px at ${box.x}, ${box.y} of the ${FRAME.w} × ${FRAME.h} frame.` : "No face box chosen: the renderer's own default is used.";
}

/** The cover's choice as the page says it. */
export function coverText(ms) {
  return Number(ms) > 0 ? `Cover: the frame at ${(Number(ms) / 1000).toFixed(1)} s of the finished video.` : "Cover: the first frame of the finished video.";
}

/** The face box a person typed in four numbers, or the reason there is none (inside the frame, a size): {box} or {reason}. */
export function faceBoxFromFields(fields) {
  const box = {};
  for (const key of ["x", "y", "w", "h"]) {
    const value = Number(fields[key]);
    if (!Number.isInteger(value) || String(fields[key]).trim() === "") return { reason: "The face box takes whole numbers of pixels." };
    box[key] = value;
  }
  if (box.w <= 0 || box.h <= 0 || box.x < 0 || box.y < 0 || box.x + box.w > FRAME.w || box.y + box.h > FRAME.h) return { reason: REASONS.bad_face_box };
  return { box };
}

/** The offset in milliseconds of seconds a person typed, or the reason there is none. */
export function coverFromSeconds(text) {
  const value = Number(String(text).trim().replace(",", "."));
  if (!Number.isFinite(value) || value < 0 || value * 1000 > COVER_MAX_MS || String(text).trim() === "") return { reason: REASONS.bad_cover };
  return { offsetMs: Math.round(value * 1000) };
}

// --- the pipeline's progress ----------------------------------------------------------------------------------------------------------------

export const STEP_WORDS = Object.freeze({
  transcribe: "Transcribe", analyse: "Look for silences", retakes: "Find retakes", "align-proposal": "Match the script", review: "Check the captions",
  remap: "Apply your words", base: "Cut and caption", align: "Place the overlays", check: "Check the edit", render: "Render the video", cover: "Cut the cover",
  approval: "Wait for your approval",
});
export const STATUS_WORDS = Object.freeze({ done: "done", waiting: "waiting for you", failed: "failed", pending: "not yet" });

/** The steps of a pipeline summary as rows [{step, label, status, word}], in the order the service gave. */
export function stepRows(steps) {
  return Object.entries(steps || {}).map(([step, status]) => ({ step, label: STEP_WORDS[step] || step, status, word: STATUS_WORDS[status] || status }));
}

/** Whether the pipeline is going on from where the person left it: the review is done and a later step is not. */
export function isRunning(steps) {
  return Boolean(steps && steps.review === "done" && Object.entries(steps).some(([step, status]) => step !== "approval" && status !== "done" && status !== "failed"));
}

/** What keeps "Done" from being pressed, as a sentence, or "": a slot with no file and no choice. */
export function doneBlock(view) {
  const open = ((view && view.slots) || []).filter((s) => (!s.file || s.file.stale) && !s.choice);
  return open.length ? `${open.length === 1 ? "An asset slot has" : `${open.length} asset slots have`} no file and no choice yet.` : "";
}
