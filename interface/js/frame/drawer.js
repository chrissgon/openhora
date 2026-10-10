// The bottom sheet of a phone (A-27): the panel of a screen (or the City's two lists) is a sheet with a handle at its top and three
// positions, collapsed (the header line only), half (the default) and full (it covers the scene). The position is a class on the sheet
// (`is-collapsed`, `is-half`, `is-full`), never a style. The sheet moves by a drag that starts on the handle or on a header, by a tap on
// the handle, and by the keyboard (the handle is a button: Enter cycles, the arrows move). A drag never starts on the sheet's scrolled
// body, so the body's scroll and the drag do not meet. While a drag lasts the sheet's height is one custom property, written through the
// CSSOM like the page's other custom properties.
//
// The position of each screen is kept in this module's memory for as long as the page lives (hash routes do not reload it). It is not
// written to the browser's storage: the file rule lets only the token module touch it, and nothing of a project or the token is kept here.
//
// The sheet tells the frame what it does with one event on itself, `wb-drawer`, which bubbles: detail {position, covering, dragging};
// `covering` is true when the sheet is at full on a phone, and the frame then pauses the scene. A released sheet says it covers nothing.

import { h } from "../dom.js";

export const POSITIONS = ["collapsed", "half", "full"];
/** M-3: the phone is every width up to 899 px; the stylesheets carry the same number (a test keeps them one). Every module that tests the width imports this. */
export const PHONE_QUERY = "(max-width: 899px)";
export const EVENT = "wb-drawer";
/** A drag shorter than this many pixels is a tap; one of at least this many always moves the sheet one step. */
export const DRAG_MIN = 24;
/** Where a drag that ends between two positions stops: the share of the available height, under which it is collapsed and over which it is full. */
export const CUT_LOW = 0.3;
export const CUT_HIGH = 0.75;
const CLICK_AFTER_DRAG_MS = 120;

const DEFAULTS = { city: "collapsed" };
const memory = new Map();

/** The position a screen opens at when nothing is remembered: the City's lists are collapsed, every panel is at half. */
export function defaultPosition(screen) {
  return DEFAULTS[screen] || "half";
}

/** A word that is one of the three positions, else null. */
export function valid(position) {
  return POSITIONS.includes(position) ? position : null;
}

/** A tap on the handle or Enter: half goes to full, full goes back to half, collapsed goes to half. */
export function cycle(position) {
  return position === "half" ? "full" : "half";
}

/** An arrow: "up" raises the sheet one position, "down" lowers it; both stop at the ends. */
export function step(position, direction) {
  const at = POSITIONS.indexOf(valid(position) || "half");
  const next = direction === "up" ? Math.min(POSITIONS.length - 1, at + 1) : Math.max(0, at - 1);
  return POSITIONS[next];
}

/**
 * Where a drag ends. `start` is the position the drag began at, `startPx` the sheet's height then, `dyPx` how far the pointer went down
 * (negative: up), `spanPx` the height the sheet can have at most. A move under DRAG_MIN is no move. Otherwise the sheet goes to the position
 * nearest the height it was dragged to; when that is the position it started at, a deliberate drag still moves it one step in its direction.
 */
export function settle(start, startPx, dyPx, spanPx) {
  const from = valid(start) || "half";
  if (!Number.isFinite(dyPx) || Math.abs(dyPx) < DRAG_MIN) return from;
  const span = Math.max(1, spanPx);
  const share = Math.min(1, Math.max(0, (startPx - dyPx) / span));
  const near = share < CUT_LOW ? "collapsed" : share < CUT_HIGH ? "half" : "full";
  return near === from ? step(from, dyPx < 0 ? "up" : "down") : near;
}

/** The label of the handle for a position (the handle is a button, so its name says what it is and where it stands). */
export function gripLabel(position) {
  return `Panel size, ${position}`;
}

/** What a screen remembers of its sheet, or null. */
export function remembered(screen) {
  return memory.get(screen) || null;
}

/** The handle: a button at the top of the sheet. Hidden by the stylesheet above the phone width. */
export function createGrip() {
  return h("button", {
    class: "wb-grip", type: "button", "aria-label": gripLabel("half"), "aria-expanded": "true",
    title: "Drag, press Enter, or use the arrow keys to move the panel",
  }, h("span", { class: "wb-grip-bar", "aria-hidden": "true" }));
}

/**
 * Make `el` a bottom sheet. options: {screen, grip (from createGrip, already a child of el), handles (a selector of the header lines that also
 * start a drag; the handle always does)}. Returns {position(), set(position), destroy()}.
 */
export function bindDrawer(el, { screen, grip, handles = ".wb-panel-head" }) {
  const phone = window.matchMedia(PHONE_QUERY);
  const selector = `.wb-grip, ${handles}`;
  let position = valid(remembered(screen)) || defaultPosition(screen);
  let drag = null;
  let draggedAt = null;     // the time stamp of the pointer-up that ended a drag: a click right after it is not a tap
  let destroyed = false;

  function tell(dragging = false, rising = false) {
    // `rising`: a drag has the sheet taller than it was when the drag began (the frame then puts the cards away); `covering` is false while a drag lasts
    el.dispatchEvent(new CustomEvent(EVENT, { bubbles: true, detail: { position, covering: phone.matches && position === "full" && !destroyed && !dragging, dragging, rising } }));
  }
  function paint() {
    for (const name of POSITIONS) el.classList.toggle(`is-${name}`, name === position);
    grip.setAttribute("aria-label", gripLabel(position));
    grip.setAttribute("aria-expanded", String(position !== "collapsed"));
  }
  function set(next) {
    const to = valid(next);
    if (!to) return;
    position = to;
    memory.set(screen, to);
    paint();
    tell();
  }

  grip.addEventListener("click", (event) => {
    if (draggedAt !== null && event.timeStamp - draggedAt < CLICK_AFTER_DRAG_MS) return;
    set(cycle(position));
  });
  grip.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    set(step(position, event.key === "ArrowUp" ? "up" : "down"));
  });

  function onDown(event) {
    if (!phone.matches || (event.button !== undefined && event.button !== 0)) return;
    if (drag) abandon();     // a gesture whose end was never heard (a lost pointerup) does not hold the sheet: this press starts afresh
    const target = event.target;
    const handle = target && target.closest ? target.closest(selector) : null;
    if (!handle || !el.contains(handle)) return;
    const control = target.closest("button, a, input, select, textarea, summary, [role=\"tab\"]");
    if (control && control !== grip) return;   // a button of the header is a button, not a handle
    drag = { id: event.pointerId, y0: event.clientY, px0: el.getBoundingClientRect().height, start: position, moved: false, onGrip: handle === grip };
    // The rest of the gesture is heard on the window: a pointer that leaves the sheet while it moves (a fast drag upward) is still the drag's, and the
    // handle keeps the click that a tap on it makes (a pointer captured by the sheet would send that click to the sheet).
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
  }
  function abandon() {
    drag = null;
    endGesture();
    el.classList.remove("is-dragging");
    el.style.setProperty("--wb-drawer-drag", "");   // an empty value removes the property
  }
  function endGesture() {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    window.removeEventListener("pointercancel", onCancel);
  }
  function onMove(event) {
    if (!drag || event.pointerId !== drag.id) return;
    const dy = event.clientY - drag.y0;
    if (!drag.moved) {
      if (Math.abs(dy) < DRAG_MIN / 4) return;
      drag.moved = true;
      el.classList.add("is-dragging");
    }
    const span = el.parentElement ? el.parentElement.clientHeight : drag.px0;
    const px = Math.min(Math.max(drag.px0 - dy, 0), span || drag.px0);
    el.style.setProperty("--wb-drawer-drag", `${Math.round(px)}px`);
    tell(true, px > drag.px0);
  }
  function onUp(event) {
    if (!drag || event.pointerId !== drag.id) return;
    const was = drag;
    drag = null;
    endGesture();
    if (!was.moved) {
      if (!was.onGrip && was.start === "collapsed") set("half");   // a tap on a header raises a collapsed sheet; a tap on the handle is its click
      return;
    }
    const span = el.parentElement ? el.parentElement.clientHeight : was.px0;
    const next = settle(was.start, was.px0, event.clientY - was.y0, span);
    el.classList.remove("is-dragging");
    el.style.setProperty("--wb-drawer-drag", "");   // an empty value removes the property
    draggedAt = event.timeStamp;
    set(next);
  }
  function onCancel(event) {
    if (!drag || event.pointerId !== drag.id) return;
    abandon();
    paint();
    tell();
  }
  el.addEventListener("pointerdown", onDown);
  const onBreakpoint = () => tell();
  phone.addEventListener("change", onBreakpoint);

  paint();
  queueMicrotask(() => { if (!destroyed) tell(); });   // the sheet is in the page by then: the frame hears of the position it opens at

  return {
    position: () => position,
    set,
    destroy() {
      if (destroyed) return;
      destroyed = true;
      if (drag) abandon();
      phone.removeEventListener("change", onBreakpoint);
      tell();   // a sheet that is gone covers nothing
    },
  };
}
