// The camera move as a small state machine, with no document, so a test can run it. One move at a time: a new move, a cancel (the
// scene was rebuilt, the preference changed, the screen was left) settles the one in flight with `false`, so whoever waits for it is
// never left hanging; finishing settles it with `true`. A move may settle with `true` earlier, at a fraction of its progress
// (`settleAt`): the screen that waits for it can be opened while the camera is still on its way, as the prototype's one camera did,
// and the move still runs to its end.
//
// The move is the prototype's (prototype-motion.js): the camera's centre and zoom (the reciprocal of the frustum's half width, as
// `cam.zoom`) each approach their goal by `1 - exp(-dt * 4.5)` a frame, stepped by frame time, so a slow frame slows the move. The goal
// may change while the camera is on its way (`retarget`: the page's panels appear when the route changes and the free rectangle
// with them): the camera carries on from where it is, no jump. A move ends when what is left is under a quarter of a pixel and snaps (a larger residual would be a visible jump on the last frame).

import { CAMERA_RATE, approach, frameSeconds } from "./prototype-motion.js";

const LAND_PIXELS = 0.25;   // the move lands when the camera is this near its goal, in screen pixels

const read = (f) => ({ x: (f.left + f.right) / 2, y: (f.top + f.bottom) / 2, zoom: 2 / (f.right - f.left), aspect: (f.top - f.bottom) / (f.right - f.left) });

function frustumOf({ x, y, zoom, aspect }) {
  const half = 1 / zoom;
  return { left: x - half, right: x + half, top: y + half * aspect, bottom: y - half * aspect };
}

// What is left of the move in screen pixels, for a view `widthPx` wide: the largest distance between a side of the camera's frustum and the same side of
// its goal.
function pixelsLeft(a, b, widthPx) {
  const f = frustumOf(a);
  const g = frustumOf(b);
  const half = f.right - f.left;
  return Math.max(Math.abs(f.left - g.left), Math.abs(f.right - g.right), Math.abs(f.top - g.top), Math.abs(f.bottom - g.bottom)) * (widthPx / half);
}

// How far the camera is from its goal, as a fraction of a screen: the centre in half widths, the zoom as a ratio.
function distance(a, b) {
  const z = (a.zoom + b.zoom) / 2;
  return Math.max(Math.abs(a.x - b.x) * z, Math.abs(a.y - b.y) * z, Math.abs(a.zoom - b.zoom) / z);
}

export function createTween() {
  let current = null;   // {cur, goal, d0, last, resolve, settleAt, settled}
  return {
    /** Start a move from one frustum to another at time `start` (ms); settles an earlier move with false. Returns a promise of the move. */
    start(from, to, start, settleAt = 1) {
      this.cancel();
      return new Promise((resolve) => {
        const cur = read(from);
        const goal = read(to);
        current = { cur, goal, d0: distance(cur, goal), last: start, resolve, settleAt, settled: false };
      });
    },
    /** Change where the move in flight is going; the camera continues from where it is. */
    retarget(to) {
      if (!current) return false;
      current.goal = read(to);
      current.d0 = Math.max(current.d0, distance(current.cur, current.goal));
      return true;
    },
    active() {
      return current !== null;
    },
    /** The frustum at `now` (ms) in a view `widthPx` pixels wide, or null when no move runs; the move ends (settles true) when it has landed. */
    step(now, widthPx = 1280) {
      if (!current) return null;
      const dt = frameSeconds(now, current.last);
      current.last = now;
      const { cur, goal } = current;
      for (const key of ["x", "y", "zoom", "aspect"]) cur[key] = approach(cur[key], goal[key], dt, CAMERA_RATE);
      const left = distance(cur, goal);
      const landed = current.d0 === 0 || pixelsLeft(cur, goal, widthPx) < LAND_PIXELS;
      if (landed) Object.assign(cur, goal);
      const progress = current.d0 === 0 ? 1 : 1 - left / current.d0;
      if (!current.settled && (landed || progress >= current.settleAt)) {
        current.settled = true;
        current.resolve(true);
      }
      const frustum = frustumOf(cur);
      if (landed) current = null;
      return frustum;
    },
    /** Stop the move and settle it with false (a cut). */
    cancel() {
      if (!current) return false;
      const done = current.resolve;
      const settled = current.settled;
      current = null;
      if (!settled) done(false);   // a move already settled with true stays true
      return true;
    },
  };
}
