// Icons: a span drawn with a CSS mask from a file of interface/icons/ (css/base.css has one rule per name). Decorative: the
// control or text beside it carries the name.

import { h } from "../dom.js";

export const ICONS = Object.freeze([
  "activity", "arrow-left-right", "building-2", "check", "chevron-down", "chevron-left", "chevron-right", "chevron-up", "circle-alert", "clock", "copy",
  "credit-card", "file-text", "folder-minus", "folder-plus", "inbox", "info", "key-round", "maximize", "message-square", "minus", "monitor",
  "moon", "plus", "send", "server", "sun", "triangle-alert", "x",
]);

/** An icon of `name` at `size` pixels (12, 14, 16 or 18). */
export function icon(name, size = 16) {
  return h("span", { class: `wb-icon wb-icon-${name} wb-i${size}`, "aria-hidden": "true" });
}
