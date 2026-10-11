// swipe.js (A-77): on a phone a horizontal swipe on a tab panel moves to the next or the previous tab of that tab's bar. One small module for every tab bar
// (the Floor's, the Lobby's, the Control room's): a screen hands it the panel, the order of its tabs, the tab now shown and the function its tab buttons
// call, so a swipe is a click on the neighbouring tab and nothing else: the keyboard path, the hash and the ARIA state of the tabs are the screen's own.
//
// A swipe counts when it is long enough, mostly horizontal, quick enough and one finger; it moves one tab (never past the first or the last). It never
// starts on a field, a range, a canvas (the 3D scene), a table or a block of code that scrolls sideways, or on what the screen marks `data-no-swipe`.
// It listens to touch only (a mouse drag does nothing) and only at phone width. Under reduced motion no slide is drawn: the tab just changes.

import { PHONE_QUERY } from "./frame/drawer.js";

export const MIN_DISTANCE = 56;      // px a swipe travels sideways at least
export const MIN_RATIO = 2;          // sideways travel over vertical travel at least: mostly horizontal
export const MAX_MS = 800;           // a slower drag is a scroll or a selection, not a swipe
const SLIDE_MS = 200;

// what takes a touch for itself: a swipe that starts on one of these is theirs (selecting text, moving a range, a scene's pan)
const OWN = "input, textarea, select, [contenteditable]:not([contenteditable=\"false\"]), [role=\"slider\"], [role=\"textbox\"], canvas, [data-no-swipe]";

/**
 * The tab a swipe goes to, or null for no tab. dx and dy are the finger's travel (end minus start) in px and ms the time it took. A swipe to the
 * left (dx < 0) goes to the next tab and one to the right to the previous; there is no wrap-around. `ids` is the order of the tabs, `current` the one shown.
 */
export function swipeTarget(ids, current, dx, dy, ms) {
  if (!Array.isArray(ids) || !ids.length || !Number.isFinite(dx) || !Number.isFinite(dy)) return null;
  if (Math.abs(dx) < MIN_DISTANCE || Math.abs(dx) < MIN_RATIO * Math.abs(dy) || !(ms <= MAX_MS)) return null;
  const at = ids.indexOf(current);
  if (at < 0) return null;
  const next = at + (dx < 0 ? 1 : -1);
  return next >= 0 && next < ids.length ? ids[next] : null;
}

/** Whether a node scrolls sideways: wider inside than shown, and its overflow lets the person scroll it. */
function scrollsSideways(node) {
  if (!(node.scrollWidth > node.clientWidth + 1)) return false;
  return /^(auto|scroll)$/.test(getComputedStyle(node).overflowX);
}

/** Whether a touch that began on `start` belongs to something inside `root` that handles it itself (see the top of the file). */
export function ownsTouch(start, root) {
  for (let node = start; node; node = node.parentElement) {
    if (node.matches && node.matches(OWN)) return true;
    if (node !== root && scrollsSideways(node)) return true;     // `root` itself is the panel: its own sideways scroll is not a table's
    if (node === root) return false;
  }
  return false;
}

const reducedMotion = () => typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Bind the swipe to a panel. options: {ids() (the order of the tabs), current() (the tab shown), go(id) (what a tab button calls), enabled() (optional:
 * false while the screen shows something that is not a tab, such as a document or a message), phone() (optional, for a test: true at phone width)}.
 * Returns {destroy()}.
 */
export function bindSwipe(root, options) {
  const phone = options.phone || (() => typeof window.matchMedia === "function" && window.matchMedia(PHONE_QUERY).matches);
  let start = null;
  let timer = 0;

  function onStart(event) {
    start = null;
    if (event.touches.length !== 1 || !phone()) return;
    if (options.enabled && !options.enabled()) return;
    if (ownsTouch(event.target, root)) return;
    const touch = event.touches[0];
    start = { x: touch.clientX, y: touch.clientY, at: Date.now() };
  }

  function onEnd(event) {
    const begun = start;
    start = null;
    if (!begun || !event.changedTouches || event.changedTouches.length !== 1) return;
    const touch = event.changedTouches[0];
    const dx = touch.clientX - begun.x;
    const id = swipeTarget(options.ids(), options.current(), dx, touch.clientY - begun.y, Date.now() - begun.at);
    if (id === null) return;
    slide(dx < 0 ? "next" : "prev");
    options.go(id);
  }

  /** The panel slides in from the side the swipe came from, briefly; nothing under reduced motion. */
  function slide(direction) {
    if (reducedMotion()) return;
    root.classList.remove("is-swipe-next", "is-swipe-prev");
    void root.offsetWidth;      // restart the animation when swipes follow each other
    root.classList.add(`is-swipe-${direction}`);
    clearTimeout(timer);
    timer = setTimeout(() => root.classList.remove("is-swipe-next", "is-swipe-prev"), SLIDE_MS + 50);
  }

  const reset = () => { start = null; };
  root.addEventListener("touchstart", onStart, { passive: true });
  root.addEventListener("touchend", onEnd, { passive: true });
  root.addEventListener("touchcancel", reset, { passive: true });
  return {
    destroy() {
      clearTimeout(timer);
      root.removeEventListener("touchstart", onStart);
      root.removeEventListener("touchend", onEnd);
      root.removeEventListener("touchcancel", reset);
    },
  };
}
