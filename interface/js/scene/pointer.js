// What the person's pointer and keys do on the canvas, as a small state machine with no three.js and no document, so a test can
// drive it with fake events and a fake clock. One pointer down is a pan (a press that moves more than DRAG_PX pixels) or, when it
// does not move, a click; two are a pinch; the wheel zooms; the keys zoom, pan and fit. The hover pick is throttled but the last
// move of a motion is never dropped, and never picked after the pointer left. The engine supplies what only it knows (the pick,
// the hover, the camera) through `env`.

import { isDrag, keyAction, wheelFactor } from "./camera.js";

export const PICK_EVERY_MS = 40;
export const CLICK_AFTER_DRAG_MS = 60;   // a click this soon after a drag ended is the drag's, not a click

/**
 * env: clock(), setTimer(fn, ms) -> id, clearTimer(id), pick(event) -> {x, y, hit}, showHover(result), open(id), canMove(),
 * pan(dx, dy), zoomBy(factor, clientX, clientY) (the client point is null for the middle), moveBy(fx, fy), resetView(),
 * dragging(on), capture(pointerId, on), hovering() -> true when an object is outlined, disposed() -> boolean.
 */
export function createPointer(env) {
  const down = new Map();   // pointerId -> {x, y}
  let press = null;         // {x, y, dragging}
  let pinch = null;         // {distance}
  let sticky = null;        // the object a touch tap has outlined, waiting for a second tap
  let lastPick = -Infinity;
  let dragEndedAt = -Infinity;
  let lastMouse = null;     // where the mouse last was over the canvas, to pick again when the camera moves under it
  let pendingMove = null;   // the latest move the throttle held back
  let pendingTimer = null;

  function cancelPending() {
    if (pendingTimer !== null) env.clearTimer(pendingTimer);
    pendingTimer = null;
    pendingMove = null;
  }

  function runPending(event) {
    const move = event && event.clientX !== undefined ? event : pendingMove;
    pendingMove = null;
    pendingTimer = null;
    if (!move || env.disposed() || sticky || down.size > 0) return;
    lastPick = env.clock();
    env.showHover(env.pick(move));
  }

  // The pick is throttled, but the last move of a motion is never dropped: a move that comes too soon is picked once more when
  // the interval is over, with the pointer's latest position.
  function hoverAt(event) {
    const wait = PICK_EVERY_MS - (env.clock() - lastPick);
    if (wait > 0) {
      pendingMove = event;
      if (pendingTimer === null) pendingTimer = env.setTimer(runPending, wait);
      return;
    }
    runPending(event);
  }

  return {
    down(event) {
      if (event.pointerType === "mouse" && event.button !== 0) return;
      down.set(event.pointerId, { x: event.clientX, y: event.clientY });
      env.capture(event.pointerId, true);
      if (down.size === 1) press = { x: event.clientX, y: event.clientY, dragging: false };
      else if (down.size === 2) {
        const [a, b] = [...down.values()];
        pinch = { distance: Math.hypot(a.x - b.x, a.y - b.y) };
        if (press) press.dragging = true;
      }
    },

    move(event) {
      const was = down.get(event.pointerId);
      if (was) {
        const dx = event.clientX - was.x;
        const dy = event.clientY - was.y;
        down.set(event.pointerId, { x: event.clientX, y: event.clientY });
        if (down.size >= 2 && pinch) {
          const [a, b] = [...down.values()];
          const distance = Math.hypot(a.x - b.x, a.y - b.y);
          if (pinch.distance > 0 && distance > 0) env.zoomBy(distance / pinch.distance, (a.x + b.x) / 2, (a.y + b.y) / 2);
          pinch.distance = distance;
          return;
        }
        if (press) {
          if (!press.dragging && isDrag(event.clientX - press.x, event.clientY - press.y)) {
            press.dragging = true;
            cancelPending();
            env.dragging(true);
            if (env.hovering() && !sticky) env.showHover({ hit: null });
          }
          if (press.dragging && env.canMove()) env.pan(dx, dy);
        }
        return;
      }
      if (event.pointerType === "touch" || sticky) return;
      lastMouse = { clientX: event.clientX, clientY: event.clientY };
      hoverAt(event);
    },

    up(event) {
      if (!down.has(event.pointerId)) return;
      down.delete(event.pointerId);
      env.capture(event.pointerId, false);
      if (down.size < 2) pinch = null;
      if (down.size === 0) {
        if (press && press.dragging) {
          dragEndedAt = env.clock();   // the click that follows is the drag's end, not a click
          env.dragging(false);
        }
        press = null;
      }
    },

    /** The pointer left the canvas: no hover, and nothing the throttle held back is picked afterwards. */
    leave() {
      lastMouse = null;
      cancelPending();
      if (!sticky && down.size === 0) env.showHover({ hit: null });
    },

    click(event) {
      if (env.clock() - dragEndedAt < CLICK_AFTER_DRAG_MS) return;
      const result = env.pick(event);
      if (!result.hit) {
        sticky = null;
        env.showHover(result);
        return;
      }
      if (event.pointerType === "touch" && sticky !== result.hit.id) {
        sticky = result.hit.id;
        env.showHover(result);
        return;
      }
      sticky = null;
      env.showHover({ hit: null });
      env.open(result.hit.id);
    },

    doubleClick(event) {
      if (!env.pick(event).hit) env.resetView();   // on the ground: the whole scene again (a double click on a building opens it)
    },

    wheel(event) {
      if (!env.canMove()) return;
      event.preventDefault();   // also with the ctrl key: a trackpad pinch arrives as ctrl + wheel and is the pinch zoom
      env.zoomBy(wheelFactor(event.deltaY, event.deltaMode), event.clientX, event.clientY);
    },

    key(event) {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      const action = keyAction(event.key);
      if (!action) return;
      event.preventDefault();
      if (action.fit) env.resetView();
      else if (action.zoom) env.zoomBy(action.zoom, null, null);
      else if (action.pan) env.moveBy(action.pan[0], action.pan[1]);
    },

    /** The camera moved under a still mouse: pick again where the mouse is. */
    again() {
      if (lastMouse && !sticky && !(press && press.dragging)) hoverAt(lastMouse);
    },

    /** For the tests and the page's checks. */
    state() {
      return { pending: pendingTimer !== null, down: down.size, dragging: Boolean(press && press.dragging), sticky, lastMouse };
    },

    dispose() {
      cancelPending();
    },
  };
}
