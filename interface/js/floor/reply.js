// A card's rendered reply that never scrolls inside the card (A-67, M-25). The reply shows a preview, about eight lines, cut with a fade to the card's ground, and a button
// "Show the whole reply" that opens it to its full height ("Show less" closes it); the page's panel is the only scroll. A reply that fits the preview shows whole with no
// button. Whether it fits is MEASURED, not guessed from its text: the body is clamped by the stylesheet (`.wb-reply:not(.is-open) .wb-reply-body`), and it is taller than the
// preview when its `scrollHeight` is more than its `clientHeight`; a ResizeObserver asks again when the body's size changes (a width change, a `details` that was just
// opened, a reply drawn again). The choice is per reply, kept by the caller for as long as the reply lives (`open`, `onToggle`), never stored.

import { h } from "../dom.js";

let counter = 0;

export const SHOW_WHOLE = "Show the whole reply";
export const SHOW_LESS = "Show less";

/** The default measure: the content is taller than the clamped body. */
export function overflows(body) {
  return body.scrollHeight > body.clientHeight + 1;
}

/**
 * Wrap `content` (a node or an array of nodes: the rendered Markdown, or the text as it came). options: {open (the reply is open now), onToggle(open) (the caller keeps the choice),
 * measure(body) -> whether the content is taller than the preview (a test gives its own)}. Returns {el, update(), isOpen(), toggle()}; `update` measures again.
 */
export function replyView(content, { open = false, onToggle = null, measure = overflows } = {}) {
  counter += 1;
  const id = `wb-reply-${counter}`;
  let isOpen = Boolean(open);
  const body = h("div", { class: "wb-reply-body", id }, ...[content].flat(Infinity));
  const button = h("button", { class: "pui-btn pui-link wb-reply-toggle", type: "button", "aria-expanded": String(isOpen), "aria-controls": id, text: isOpen ? SHOW_LESS : SHOW_WHOLE });
  const root = h("div", { class: `wb-reply${isOpen ? " is-open" : ""}` }, body);
  const showButton = (on) => {      // the button is in the page only when the reply is cut or open: a reply that fits has no button at all
    if (on && button.parentNode !== root) root.append(button);
    else if (!on && button.parentNode === root) button.remove();
  };

  function update() {
    if (isOpen) {      // open: the button stays, so that the reply can be closed
      showButton(true);
      root.classList.remove("is-cut");
      return;
    }
    const cut = Boolean(measure(body));
    root.classList.toggle("is-cut", cut);
    showButton(cut);
  }

  function toggle() {
    isOpen = !isOpen;
    root.classList.toggle("is-open", isOpen);
    button.setAttribute("aria-expanded", String(isOpen));
    button.textContent = isOpen ? SHOW_LESS : SHOW_WHOLE;
    if (onToggle) onToggle(isOpen);
    update();
    if (!isOpen && button.scrollIntoView) button.scrollIntoView({ block: "nearest" });     // closed: the page gets shorter under the reader; the button stays in view
  }
  button.addEventListener("click", toggle);
  // the focus enters the clipped part (a link, the Plain text toolbar inside it): the reply opens, so that what has the focus is never hidden
  root.addEventListener("focusin", (event) => {
    if (!isOpen && event.target !== button && body.contains(event.target)) toggle();
  });

  // Without a way to measure (no ResizeObserver and no measure of its own) the reply is not clipped: it shows whole, with no button, rather than cut with no way to open it
  const measurable = typeof ResizeObserver === "function" || measure !== overflows;
  if (typeof ResizeObserver === "function") new ResizeObserver(() => update()).observe(body);
  if (measurable) update();
  else root.classList.add("is-open");
  return { el: root, update, isOpen: () => isOpen, toggle };
}
