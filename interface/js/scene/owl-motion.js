// The owl's three motions (round 4, `base.css`: `m-owl-wave`, `m-owl-tap`, `m-owl-snore`, `m-owl-zz`), as functions of time: the raised wing of the waiting owl
// waves, the two wings of the working owl tap in turn, the idle owl breathes and three z rise from it. Pure: no three.js, no document. The numbers are the
// stylesheet's keyframes, each property eased between its own keyframes as the browser eased the drawing (`ease-in-out`, and `ease-out` for the z). A pose that
// is still (reduced motion) is `REST`, never a changed number here. Angles are CSS degrees (clockwise is positive); offsets are in the drawing's units, y down.

import { cubicBezier, easeInOut, sample } from "./city-motion.js";

export const WAVE_SECONDS = 1.6;
export const TAP_SECONDS = 0.36;
export const TAP_DELAY = -0.18;     // the far wing is half a beat behind (`.m-owl-hand.is-b`)
export const SNORE_SECONDS = 3.2;
export const ZZ_SECONDS = 3.2;
export const BLINK_SECONDS = 4.8;      // the ready owl's slow blink (M-24): once every few seconds, the lids down and up again in a quarter of a second
export const ZZ_DELAYS = Object.freeze([0, 0.5, 1]);

const easeOut = cubicBezier(0, 0, 0.58, 1);
const phase = (seconds, period, delay = 0) => ((((seconds - delay) / period) % 1) + 1) % 1;

/** The raised wing's turn at `seconds`: -6 to 12 degrees and back, about a point at 20 percent from its left and 90 percent down (`m-owl-wave`). */
export function wavePose(seconds) {
  return sample([[0, -6], [0.5, 12], [1, -6]], phase(seconds, WAVE_SECONDS), easeInOut);
}

/** A typing wing's turn: -5 to 3 degrees and back about its top left (`m-owl-tap`); the far wing (`far`) is half a beat behind. */
export function tapPose(seconds, far = false) {
  return sample([[0, -5], [0.5, 3], [1, -5]], phase(seconds, TAP_SECONDS, far ? TAP_DELAY : 0), easeInOut);
}

/** The sleeping owl's breath: {x, y} scales about its feet, 1 to 1.035 and 1.05 at 45 percent of 3.2 s (`m-owl-snore`). */
export function snorePose(seconds) {
  const [x, y] = sample([[0, [1, 1]], [0.45, [1.035, 1.05]], [1, [1, 1]]], phase(seconds, SNORE_SECONDS), easeInOut);
  return { x, y };
}

/** The ready owl's lids at `seconds`: 0 (open) for most of the period, then 1 (the eyes shut) for an instant at its end and open again (`BLINK_SECONDS`). */
export function blinkPose(seconds) {
  return sample([[0, 0], [0.9, 0], [0.925, 1], [0.95, 0], [1, 0]], phase(seconds, BLINK_SECONDS), easeInOut);
}

/**
 * Letter `k` (0 to 2) of the three z at `seconds`: {opacity, dx, dy, scale}, each starting half a second after the one before. It appears small and a little
 * low, settles where the drawing has it, stays, and goes off up and to the right fading (`m-owl-zz`, `ease-out`).
 */
export function zzPose(seconds, k) {
  const delay = ZZ_DELAYS[k] || 0;
  // before its delay the letter is as its stylesheet rule leaves it (opacity 0), which is the first keyframe
  const [opacity, dx, dy, scale] = sample([[0, [0, -8, 10, 0.7]], [0.15, [0, -8, 10, 0.7]], [0.4, [1, 0, 0, 1]], [0.7, [1, 0, 0, 1]], [1, [0, 6, -12, 1]]],
    seconds < delay ? 0 : phase(seconds, ZZ_SECONDS, delay), easeOut);
  return { opacity, dx, dy, scale };
}

/** Every pose still (reduced motion): the wing and the wings at rest, the ready owl's eyes open, no breath, the three z shown in the places the drawing gives them. */
export const REST = Object.freeze({ wave: 0, tap: 0, blink: 0, snore: Object.freeze({ x: 1, y: 1 }), zz: Object.freeze({ opacity: 1, dx: 0, dy: 0, scale: 1 }) });
