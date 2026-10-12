// The two motions of the City's states (round 4, `scene.css`), as functions of time: the agent's shadow at the windows of a lit floor (R-19, the
// keyframes `wb-agent`, 48 s) and the decision mark's notification (R-20, `wb-alert`, 3.4 s). Pure: no three.js, no document. The keyframes are the
// stylesheet's own numbers, each property interpolated between its own keyframes with `ease-in-out` (cubic-bezier .42 0 .58 1), as the browser did
// for the drawing. What the product adds around them (30 frames a second at most, none while hidden, one still figure under reduced motion) is the
// loop's and the engine's. A motion that is still is `rest`, never a changed number here.

export const AGENT_SECONDS = 48;
export const ALERT_SECONDS = 3.4;

/** The CSS timing function `cubic-bezier(x1, y1, x2, y2)` as a function of progress, solved for x by bisection. */
export function cubicBezier(x1, y1, x2, y2) {
  const axis = (a, b, t) => 3 * a * (1 - t) * (1 - t) * t + 3 * b * (1 - t) * t * t + t * t * t;
  return (x) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let lo = 0;
    let hi = 1;
    for (let i = 0; i < 32; i++) {
      const mid = (lo + hi) / 2;
      if (axis(x1, x2, mid) < x) lo = mid; else hi = mid;
    }
    return axis(y1, y2, (lo + hi) / 2);
  };
}

export const easeInOut = cubicBezier(0.42, 0, 0.58, 1);

/** The value at progress `p` (0 to 1) of a track [[position, ...values]], eased between neighbouring keyframes (`ease-in-out` unless another timing function is given); a value is a number or an array of numbers. */
export function sample(track, p, ease = easeInOut) {
  const t = ((p % 1) + 1) % 1;
  let k = 0;
  while (k < track.length - 2 && t >= track[k + 1][0]) k += 1;
  const [p0, v0] = track[k];
  const [p1, v1] = track[k + 1];
  const e = ease(p1 === p0 ? 1 : Math.min(1, Math.max(0, (t - p0) / (p1 - p0))));
  return Array.isArray(v0) ? v0.map((a, i) => a + (v1[i] - a) * e) : v0 + (v1 - v0) * e;
}

// `wb-agent`: opacity and the transform (translate x, translate y, scale) are separate keyframe lists in the stylesheet.
const AGENT_OPACITY = [[0, 0], [0.025, 0.4], [0.07, 0.62], [0.195, 0.62], [0.23, 0.35], [0.25, 0], [1, 0]];
export const AGENT_REST_OPACITY = 0.62;   // `.m-agent:nth-child(2)` under reduced motion

/** The distances of a figure's walk in the window's plane, in world units: it comes from `COME` to the side, leaves by `LEAVE` and up by `LEAVE_UP`. */
export const COME = 0.85;
export const LEAVE = 0.68;
export const LEAVE_UP = 0.3;
/**
 * The page's start is `translate(--ax, --ay)` with `--ax` -13.2 px and `--ay` -7.2 px: along the face's horizontal axis the same step would be -7.62 px
 * (13.2 times tan 30), so the start sits 0.42 px lower than a level slide; at 18.75 px to the unit that is this much (x and y arrive together).
 */
export const COME_Y = -0.022;

/**
 * The shadow of window `k` of floor `floor` at `seconds` of the clock: {opacity, x, y, scale} in the window's plane (x along the wall, y up from
 * the window's foot). Each window has its own phase and the floors are shifted against one another, so the four windows of a floor take
 * their turns one after the other, in an uneven order, and no two floors move together. `side` (-1 or 1) is the side it comes from.
 */
export function agentPose(seconds, k, floor) {
  const side = windowSide(k, floor);
  const phase = (((seconds + windowOffset(k, floor)) % AGENT_SECONDS) + AGENT_SECONDS) % AGENT_SECONDS / AGENT_SECONDS;
  const transform = sample([[0, [side * COME, COME_Y, 0.28]], [0.07, [0, 0, 1]], [0.195, [0, 0, 1]], [0.25, [-side * LEAVE, LEAVE_UP, 0.3]], [1, [-side * LEAVE, LEAVE_UP, 0.3]]], phase);
  return { opacity: sample(AGENT_OPACITY, phase), x: transform[0], y: transform[1], scale: transform[2], phase };
}

/** The phase offset, in seconds, of window k of a floor: the stylesheet's negative animation delays (35, 59, 47, 23), the odd floors 4.5 s earlier. */
export function windowOffset(k, floor) {
  return [35, 59, 47, 23][k % 4] - 4.5 * (floor % 2);
}

/** The side window k comes from on floor `floor`: alternating along a floor, the same on two floors in a row, then flipped. */
export function windowSide(k, floor) {
  return (k + Math.floor(floor / 2)) % 2 === 0 ? -1 : 1;
}

/** The pose of a still figure (reduced motion): window k of a floor shows the figure at its window when k is 1, nothing for the others. */
export function agentRest(k) {
  return { opacity: k === 1 ? AGENT_REST_OPACITY : 0, x: 0, y: 0, scale: 1, phase: 0 };
}

// `wb-alert`: it rises a little, shakes left and right, settles, rests. Rise in world units, roll in degrees.
export const ALERT_RISE = 0.3;
const ALERT_TRACK = [
  [0, [0, 0]], [0.58, [0, 0]], [0.64, [ALERT_RISE, 0]], [0.69, [ALERT_RISE, -13]], [0.74, [ALERT_RISE, 11]], [0.79, [ALERT_RISE, -8]],
  [0.84, [ALERT_RISE, 5]], [0.89, [ALERT_RISE, 0]], [0.95, [0, 0]], [1, [0, 0]],
];

/** The decision mark at `seconds` of the clock: {rise, roll} (roll in degrees, about the view axis through the mark's foot). */
export function alertPose(seconds) {
  const [rise, roll] = sample(ALERT_TRACK, (((seconds % ALERT_SECONDS) + ALERT_SECONDS) % ALERT_SECONDS) / ALERT_SECONDS);
  return { rise, roll };
}
