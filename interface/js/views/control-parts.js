// Small pieces the three tabs of the Control room share: the loading block, the soft error notice, the empty block, a chip,
// a section heading, a meter. Everything from the service is put in as text.

import { h } from "../dom.js";
import { icon } from "../frame/icons.js";

export const FAILED_TITLE = "The read failed";

/** The loading block (the page's: the dashed block with the static ring and the sentence), `aria-busy`. */
export function loadingCard(text) {
  return h("div", { class: "wb-empty-block wb-loading", "aria-busy": "true" }, h("span", { class: "wb-ring", "aria-hidden": "true" }), ` ${text}`);
}

/**
 * A notice in the soft error style (R-11, R-54): the library's `notice pui-soft pui-error`, an icon at its start, a bold title and one line under it for each of `lines`.
 * A line is plain text, or {text, mono: true} for what the service said (in the monospace face, free to break anywhere). `role="alert"`.
 */
export function noticeCard(title, lines) {
  return h("div", { class: "notice pui-soft pui-error wb-cnotice", role: "alert" },
    h("span", { class: "wb-cnotice-icon" }, icon("triangle-alert", 16)),
    h("div", {},
      h("strong", { class: "wb-cnotice-title", text: title }),
      lines.map((line) => {
        const spec = typeof line === "string" ? { text: line } : line;
        return h("p", { class: `${spec.mono ? "mono " : ""}wb-cnotice-line`, text: spec.text });
      })));
}

/** The notice of a read that failed or a date the service refused: a title over the service's own message (text, in the monospace face). */
export function failedCard(title, message) {
  return noticeCard(title, [{ text: message, mono: true }]);
}

/** The dashed block that says a list is empty. */
export function emptyBlock(text) {
  return h("div", { class: "wb-empty-block", text });
}

/** A chip in the library's classes, at the page's size (12 px). */
export function chip(className, text) {
  return h("span", { class: `${className} wb-chip-12`, text });
}

/** A section heading above a table or a card: small, as the page draws it (`h3.wb-sec-head`). */
export function sectionHead(text) {
  return h("h3", { class: "wb-sec-head", text });
}

/** A value in the monospace face. */
export function code(text) {
  return h("code", { class: "wb-code", text });
}

/** A table cell with the label a phone prints before it when the table is stacked. */
export function cell(label, ...children) {
  return h("td", { "data-label": label }, ...children);
}

/** A number cell: right-aligned, tabular figures. */
export function numCell(label, ...children) {
  return h("td", { "data-label": label, class: "wb-num" }, ...children);
}

/**
 * A meter (the KPI cards' and the Floor's): a track with a fill, and, when part of it is reserved for runs whose cost is not recorded yet, a second segment of its own
 * tint. The shares are fractions of the cap (0 to 1); a script writes the one custom property `--wb-share` through the CSS Object Model, never a style attribute.
 * `full` turns the fill to the warn colour (the cap is reached).
 */
export function meter(share, { reserved = 0, full = false } = {}) {
  const fill = h("span", { class: `wb-meter-fill${full ? " is-full" : ""}` });
  fill.style.setProperty("--wb-share", `${Math.round(share * 100)}%`);
  const segments = [fill];
  if (reserved > 0) {
    const second = h("span", { class: "wb-meter-reserved" });
    second.style.setProperty("--wb-share", `${Math.round(reserved * 100)}%`);
    segments.push(second);
  }
  return h("span", { class: `wb-meter${reserved > 0 ? " has-reserved" : ""}`, "aria-hidden": "true" }, segments);
}

/**
 * Make `parent`'s children exactly `nodes`, in order, without removing and re-inserting a node that is already in place: a
 * focused field kept in the list keeps its focus (replaceChildren would drop it). New nodes are inserted before the node
 * that stands where they belong; nodes not in the list are removed.
 */
export function reconcile(parent, nodes) {
  nodes.forEach((node, i) => {
    const here = parent.children[i];
    if (here !== node) parent.insertBefore(node, here || null);
  });
  while (parent.children.length > nodes.length) parent.children[nodes.length].remove();
}

/** A card that holds a table (the page's `pui-card wb-tcard`: it scrolls sideways inside itself when the table is wider). */
export function tableCard(table, className = "") {
  return h("div", { class: `pui-card wb-tcard${className ? ` ${className}` : ""}` }, table);
}
