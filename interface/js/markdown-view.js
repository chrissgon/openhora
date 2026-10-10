// A Markdown text with its "Plain text" toggle (WP-9.17): the rendered view and the text exactly as it came, one of them hidden, and
// a button that swaps them. The choice is the person's, kept for the page session (a module variable: a reload forgets it) and
// shared by every view made here (the document viewer, the plan cards and the Inbox's cards). The renderer is markdown.js; this file only places it.

import { h } from "./dom.js";
import { renderMarkdown } from "./markdown.js";

let plainChosen = false;

/** The session's choice of "Plain text" (R-34: one for the session; the Inbox's cards read and set it too, through these two). */
export function plainChoice() {
  return plainChosen;
}

export function setPlainChoice(value) {
  plainChosen = Boolean(value);
}

/**
 * The nodes of one text: [toolbar with the toggle, rendered view, plain `pre`]. options: {name (what the text is: the plain `pre` is "Text of <name>"), renderedLabel
 * (what a screen reader calls the rendered view, default the name), plainClass (the class of the `pre`)}. Put them in one container; one of the two views is hidden.
 */
export function markdownView(text, { name, renderedLabel = name, plainClass }) {
  const value = String(text);
  const pre = h("pre", { class: plainClass, tabindex: "0", "aria-label": `Text of ${name}` }, value);
  const rendered = renderMarkdown(value);
  rendered.setAttribute("tabindex", "0");
  rendered.setAttribute("aria-label", renderedLabel);
  const toggle = h("button", { class: "pui-btn pui-surface pui-outline wb-small-button", type: "button", "data-key": "plain", "aria-pressed": String(plainChosen), text: "Plain text" });
  const show = () => {
    rendered.hidden = plainChosen;
    pre.hidden = !plainChosen;
    toggle.setAttribute("aria-pressed", String(plainChosen));
  };
  toggle.addEventListener("click", () => {
    plainChosen = !plainChosen;
    show();
  });
  show();
  return [h("div", { class: "wb-md-tools" }, toggle), rendered, pre];
}
