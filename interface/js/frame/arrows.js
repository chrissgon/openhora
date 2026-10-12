// Arrow-key movement in a list of links or options: Down and Up move the focus, Home and End jump. Enter and Space are the
// elements' own.

/** Make the focusable children matching `selector` of `list` movable by the arrow keys. */
export function arrowNav(list, selector) {
  list.addEventListener("keydown", (event) => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    const items = [...list.querySelectorAll(selector)];
    if (!items.length) return;
    const at = items.indexOf(document.activeElement);
    let next = at;
    if (event.key === "ArrowDown") next = Math.min(items.length - 1, at + 1);
    else if (event.key === "ArrowUp") next = Math.max(0, at < 0 ? 0 : at - 1);
    else if (event.key === "Home") next = 0;
    else next = items.length - 1;
    event.preventDefault();
    items[Math.max(0, next)].focus();
  });
}

/**
 * Run `render` (which replaces the children of `container`) and put the keyboard focus back on the link with the same
 * href when it was inside: a list redrawn by a poll must not take the focus from a person using it.
 */
export function keepFocus(container, render) {
  const active = document.activeElement;
  const href = active && container.contains(active) && active.getAttribute ? active.getAttribute("href") : null;
  render();
  if (!href) return;
  const next = [...container.querySelectorAll("a")].find((a) => a.getAttribute("href") === href);
  if (next) next.focus({ preventScroll: true });
}
