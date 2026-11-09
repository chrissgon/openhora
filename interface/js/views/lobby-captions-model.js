// The caption review's pure part (package V1c-2): which words are selected, the closed edit objects the dialog sends (the objects of runtime/captions.py), the fields of
// a catalogue block's parameters and the rules that check what a person typed there. No DOM, no client and no state: views/lobby-captions.js draws and sends. The page
// only builds the shapes the service accepts; the service (captions-edit) decides again, and its sentence for a refusal is shown as it came.

/** The word of a view's `words` with this `index` (the list is in order, but an index is a number the service gave, not a position), or undefined. */
function wordAt(words, index) {
  return (Array.isArray(words) ? words : []).find((w) => w && w.index === index);
}

/** The selection after a click on the word `index`: a click starts a new range at that word. A word the list does not hold leaves the selection as it was. */
export function selection(prev, index, words) {
  return wordAt(words, index) ? { from: index, to: index } : (prev || null);
}

/** The range with one more word on its right, within the segment of its last word; unchanged at the segment's end or at the end of the list. */
export function grow(sel, words) {
  if (!sel) return sel;
  const last = wordAt(words, sel.to);
  const next = wordAt(words, sel.to + 1);
  if (!last || !next || next.segment !== last.segment) return sel;
  return { from: sel.from, to: sel.to + 1 };
}

/** The range with one word less on its right; never below one word. */
export function shrink(sel) {
  if (!sel || sel.to <= sel.from) return sel;
  return { from: sel.from, to: sel.to - 1 };
}

/** True when every word of the range is in the list and they all share one `segment` (a merge is refused across segments). */
export function sameSegment(sel, words) {
  if (!sel) return false;
  const first = wordAt(words, sel.from);
  if (!first) return false;
  for (let i = sel.from; i <= sel.to; i += 1) {
    const w = wordAt(words, i);
    if (!w || w.segment !== first.segment) return false;
  }
  return true;
}

/**
 * The closed edit of a word action, or null when the action does not fit the selection: "edit" {op, index, text} and "delete" {op, index} need one word;
 * "merge" {op, from, to, text} needs two or more words of one segment.
 */
export function editOf(kind, sel, words, text) {
  if (!sel) return null;
  if (kind === "edit" && sel.from === sel.to) return { op: "edit", index: sel.from, text: String(text) };
  if (kind === "delete" && sel.from === sel.to) return { op: "delete", index: sel.from };
  if (kind === "merge" && sel.from < sel.to && sameSegment(sel, words)) return { op: "merge", from: sel.from, to: sel.to, text: String(text) };
  return null;
}

/** Cut (confirmed true) or keep (false) one proposed retake. */
export function retakeEdit(id, confirmed) {
  return { op: "retake", id, confirmed: Boolean(confirmed) };
}

/** Anchor a beat to the selected words. */
export function anchorEdit(beat, sel) {
  return { op: "anchor", beat, word_from: sel.from, word_to: sel.to };
}

/** Clear the anchor of a beat. */
export function clearAnchor(beat) {
  return { op: "anchor", beat, clear: true };
}

/** Drop (true) or keep (false) the overlay of a beat. */
export function overlayEdit(beat, dropped) {
  return { op: "overlay", beat, dropped: Boolean(dropped) };
}

/** Remove one animation of the review. */
export function removeAnimation(id) {
  return { op: "animation", id, remove: true };
}

/** Add an animation of the catalogue block `block` over the selected words, with the parameters typed. */
export function addAnimation(block, params, sel) {
  return { op: "animation", block, params, word_from: sel.from, word_to: sel.to };
}

const FIELD_TYPES = Object.freeze(["text", "choice", "number", "icon", "color"]);

/**
 * The form fields of a catalogue entry, in the entry's order: [{name, type, required, max, maxItems, values}] for the types text, choice, number, icon and color.
 * An optional parameter of another type is left out. A required parameter of another type (an image or a clip: a slot) cannot be typed: the list is empty and its
 * `unsupported` is true. The list always has an `unsupported` boolean.
 */
export function fieldsOf(entry) {
  const specs = entry && entry.params && typeof entry.params === "object" ? entry.params : {};
  const fields = [];
  fields.unsupported = false;
  for (const [name, spec] of Object.entries(specs)) {
    const type = spec && typeof spec === "object" ? spec.type : undefined;
    const known = typeof type === "string" && FIELD_TYPES.includes(type);
    if (!known) {
      if (spec && spec.required) {
        const none = [];
        none.unsupported = true;
        return none;
      }
      continue;
    }
    fields.push({
      name,
      type,
      required: Boolean(spec.required),
      max: Number.isFinite(spec.max) ? spec.max : null,
      maxItems: Number.isFinite(spec.max_items) ? spec.max_items : null,
      values: Array.isArray(spec.values) ? spec.values.map(String) : [],
    });
  }
  return fields;
}

/**
 * The params object for `addAnimation` from what was typed (`typed` maps a field name to its text): {params}, or {problem} with the sentence to show. A required
 * field left empty, a text longer than its `max`, more " | " parts than `maxItems`, a choice that is not one of the values and a number that is not one are
 * problems; an empty optional field is left out; a number field is sent as a Number and every other as a string.
 */
export function paramsOf(fields, typed) {
  const params = {};
  const given = typed && typeof typed === "object" ? typed : {};
  for (const f of Array.isArray(fields) ? fields : []) {
    const raw = given[f.name] === undefined || given[f.name] === null ? "" : String(given[f.name]);
    const text = raw.trim();
    if (!text) {
      if (f.required) return { problem: `${f.name} is required.` };
      continue;
    }
    if (f.type === "number") {
      const n = Number(text);
      if (!Number.isFinite(n)) return { problem: `${f.name} must be a number.` };
      params[f.name] = n;
      continue;
    }
    if (f.max !== null && f.max !== undefined && text.length > f.max) return { problem: `${f.name} is at most ${f.max} characters.` };
    if (f.maxItems !== null && f.maxItems !== undefined && text.split(" | ").length > f.maxItems) {
      return { problem: `${f.name} has at most ${f.maxItems} parts, separated by " | ".` };
    }
    if (f.type === "choice" && Array.isArray(f.values) && f.values.length && !f.values.includes(text)) return { problem: `${f.name} must be one of: ${f.values.join(", ")}.` };
    params[f.name] = text;
  }
  return { params };
}

/** Why a catalogue block cannot be added now, by the service's word. */
export const WHY_TEXT = Object.freeze({
  kind: "Not an animation over words.",
  no_preset: "This engine has no way to draw it.",
  slot: "It needs a picture or a clip, which comes later.",
  engine: "Not drawn by this project's engine.",
  not_configured: "The video engine is not set up for this project.",
});

/** Why the rule proposed a retake, by the service's closed word (providers/renderer/_retakes.py REASONS). */
export const RETAKE_REASONS = Object.freeze({
  redo: "a whole sentence said again in other words",
  cut_off: "it was cut off",
  hesitation: "a hesitation came before the new take",
  continues: "said again and carried on",
  abandoned: "an unfinished sentence",
  pause: "said again after a pause",
  complete: "a complete sentence said twice",
  far: "too far apart to cut by rule",
});

/** The state of a retake row in words: the rule's or the person's, cut or kept. */
export function retakeState(r) {
  const who = r.decided === "person" ? "you" : "the rule";
  return `${r.confirmed ? "cut" : "kept"} by ${who}`;
}

/** The text of the words `from` to `to` of a view's `words`, in order, as one line. */
export function wordsText(words, from, to) {
  if (!Array.isArray(words) || typeof from !== "number" || typeof to !== "number") return "";
  return words.filter((w) => w && w.index >= from && w.index <= to).map((w) => w.text).join(" ");
}

/** True when the dialog may send an edit: only at the review or at the delivery card; a null mode is read-only. */
export function canEdit(mode) {
  return mode === "review" || mode === "gate";
}
