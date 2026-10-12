// The motion of the 3D prototype, as functions: the product's scene calls these where the prototype's `World.tick` and
// `animateFloor` ran the same lines. Each function says which line of the prototype it is. Nothing here touches three.js or the page,
// so a test can run it. What the product adds around them (the 30 frame cap of ambient motion, render on demand, reduced motion, no
// motion while the tab is hidden) is the loop's (loop.js) and the engine's, never a change to the numbers here.
//
// Not ported, on purpose: the prototype's decoration (the glitter over the screen, the life of its street), the waving figure and the
// spinning marker of a waiting agent and the idle head nod: the specification lets only a state or a feature move. The typing figure of the
// prototype is gone with the figure (R-24, R-41): the agent is the owl, whose motions are `owl-motion.js`.

export const CAMERA_RATE = 4.5;      // tick(): `k = 1 - Math.exp(-dt * 4.5)`
export const EXPLODE_RATE = 3.2;     // tick(): `b.explode += (goal - b.explode) * (1 - Math.exp(-dt * 3.2))`
export const MAX_DT = 0.05;          // the prototype's loop: `dt = Math.min(0.05, (now - last) / 1000)`
export const SETTLED = 0.01;         // the product ends a move that has come within one percent of its goal (the prototype's never ends)

/** The prototype's `smooth`: the opening's pitch is read through it (`applyExplode` uses smooth(b.explode)). */
export const smooth = (t) => t * t * (3 - 2 * t);

/** The prototype's `lerp`. */
export const lerp = (a, b, t) => a + (b - a) * t;

/** One frame of the prototype's approach: `value + (goal - value) * (1 - exp(-dt * rate))`, frame-rate independent. */
export function approach(value, goal, dt, rate) {
  return value + (goal - value) * (1 - Math.exp(-dt * rate));
}

/** The seconds a frame counts for: the time since the last frame, never more than MAX_DT (a slow frame slows the move, as it did). */
export function frameSeconds(now, last) {
  return Math.max(0, Math.min(MAX_DT, (now - last) / 1000));
}

/**
 * The progress of a move from 0 to 1, stepped frame by frame as the prototype stepped `cam.zoom`, `cam.target` and `b.explode`: each of
 * them was approached by the same factor, so one progress drives them all (the camera's centre and zoom are `lerp(from, to, progress)`).
 * It lands on 1 once it is within SETTLED, which takes ln(100) / rate seconds. Returns {step(dt) -> progress, progress(), done()}.
 */
export function createApproach(rate) {
  let p = 0;
  return {
    step(dt) {
      p = approach(p, 1, dt, rate);
      if (1 - p <= SETTLED) p = 1;
      return p;
    },
    progress: () => p,
    done: () => p >= 1,
  };
}

// --- the beacon: `tick()`, `b.beacon` -----------------------------------------------------------------------------------------------

export const BEACON_RATE = 3;         // 1 + 0.12 * Math.sin(t * 3), a 2.09 s cycle
export const BEACON_SWING = 0.12;

/** The roof ring at `t` seconds: its scale in the ring's plane (the third axis stays 1) and its opacity, .35 to .65. */
export function beaconPulse(t) {
  const wave = Math.sin(t * BEACON_RATE);
  return { scale: 1 + BEACON_SWING * wave, opacity: 0.35 + 0.3 * (0.5 + 0.5 * wave) };
}
