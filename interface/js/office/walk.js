// Where each agent is and how it gets there: pure, no document, no clock of its own (the caller gives the time and the random numbers).
// An agent that works, is queued or is off sits at its seat; one that waits for the person stands at the board; an idle one sits until it
// wanders. A walk is the A* port's path, followed at SPEED tiles a second; with no path, or with reduced motion, the figure is set on its place at once.

export const SPEED = 4;               // tiles a second
export const WANDER_MS = 8000;        // an idle figure at rest this long gets up
export const STEP_FRAME_MS = 150;     // the walking figure changes its frame this often
export const WANDER_TICK_MS = 1000;   // how often the view lets time pass for figures at rest (each rests its own time, between half and one and a half WANDER_MS)

/** The tile an agent belongs on: its seat (index = the seat's number), or the board for one that waits (waitingIndex = its turn among them). */
export function placeOf(agent, index, room, waitingIndex) {
  const seat = room.seats[index].seat;
  if (agent.state === "waiting" && room.board.length) return room.board[waitingIndex % room.board.length];
  return seat;
}

/** A generator of numbers in [0, 1) from a seed (mulberry32): the view seeds it with the project's hash so that a reload does not move the figures. */
export function seeded(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * The figures of a room: {retarget(agents, {reduced}), advance(dtMs, nowMs, random), positions(), moving()}. `finder` is a PathFinder over the room's grid.
 * agents: the drawn ones, in seat order: [{name, state}].
 */
export function createWalkers(room, finder) {
  const walkers = new Map();
  let reduced = false;
  const out = [];

  function place(walker, target) {
    walker.x = target.x;
    walker.y = target.y;
    walker.path = [];
    walker.target = target;
    walker.restMs = 0;
    walker.walkedMs = 0;
    walker.frame = 0;
  }

  /** How long this figure rests before it wanders: its own, from the random it was given (one WANDER_MS when it was given none). */
  const restFor = (random) => (random ? WANDER_MS * (0.5 + random()) : WANDER_MS);

  function goTo(walker, target) {
    const same = walker.target && walker.target.x === target.x && walker.target.y === target.y;
    if (same) return;
    if (reduced) return place(walker, target);
    // a figure part-way along a step finishes it first, then takes the new path from that tile
    const keep = walker.path.length ? walker.path.slice(0, 2) : [];
    const from = keep.length ? { x: keep[0], y: keep[1] } : { x: Math.round(walker.x), y: Math.round(walker.y) };
    if (!finder.find(from.x, from.y, target.x, target.y, out)) return place(walker, target);
    walker.path = keep.concat(out);
    walker.target = target;
    walker.restMs = 0;
  }

  return {
    /** Give each drawn agent its place for its state; a figure that already stands where it should is left alone (an idle one may be wandering). */
    retarget(agents, options = {}) {
      reduced = Boolean(options.reduced);
      const random = options.random || null;
      const names = new Set(agents.map((a) => a.name));
      for (const name of [...walkers.keys()]) if (!names.has(name)) walkers.delete(name);
      let waitingIndex = 0;
      agents.forEach((agent, index) => {
        const target = placeOf(agent, index, room, waitingIndex);
        if (agent.state === "waiting") waitingIndex += 1;
        let walker = walkers.get(agent.name);
        if (!walker) {
          walker = { name: agent.name, x: 0, y: 0, path: [], target: null, dir: "down", frame: 0, walkedMs: 0, restMs: 0, state: agent.state, home: room.seats[index].seat, wanderAfter: restFor(random) };
          walkers.set(agent.name, walker);
          place(walker, target);
          return;
        }
        walker.home = room.seats[index].seat;
        const changed = walker.state !== agent.state;
        walker.state = agent.state;
        // an idle figure that is away from its seat because it wandered stays there until it rests long enough to return
        if (agent.state === "idle" && !changed) return;
        goTo(walker, target);
      });
    },

    /** Move every figure `dtMs` along its path; an idle figure at rest for WANDER_MS gets up (or goes back to its seat). */
    advance(dtMs, nowMs, random) {
      for (const walker of walkers.values()) {
        if (walker.path.length) {
          walker.walkedMs += dtMs;
          walker.frame = Math.floor(walker.walkedMs / STEP_FRAME_MS) % 2;
          let budget = (SPEED * dtMs) / 1000;
          while (budget > 0 && walker.path.length) {
            const tx = walker.path[0];
            const ty = walker.path[1];
            const dx = tx - walker.x;
            const dy = ty - walker.y;
            const dist = Math.abs(dx) + Math.abs(dy);
            if (dx > 0) walker.dir = "right";
            else if (dx < 0) walker.dir = "left";
            else if (dy > 0) walker.dir = "down";
            else if (dy < 0) walker.dir = "up";
            if (dist <= budget) {
              walker.x = tx;
              walker.y = ty;
              walker.path.splice(0, 2);
              budget -= dist;
            } else {
              walker.x += Math.sign(dx) * budget;
              walker.y += Math.sign(dy) * budget;
              budget = 0;
            }
          }
          if (!walker.path.length) {
            walker.frame = 0;
            walker.walkedMs = 0;
            walker.restMs = 0;
          }
          continue;
        }
        walker.restMs += dtMs;
        if (walker.state !== "idle" || reduced || walker.restMs < walker.wanderAfter || !room.wander.length) continue;
        const away = walker.x !== walker.home.x || walker.y !== walker.home.y;
        const target = away ? walker.home : room.wander[Math.floor(random() * room.wander.length)];
        walker.target = null;
        goTo(walker, target);
        walker.restMs = 0;
        walker.wanderAfter = restFor(random);
      }
    },

    /** Put every figure on its place at once (reduced motion was turned on while some were walking). */
    settle() {
      for (const walker of walkers.values()) if (walker.path.length) place(walker, walker.target);
    },

    /** Every figure: [{name, x, y, dir, pose, frame}] (x and y in tiles, fractional while walking). */
    positions() {
      return [...walkers.values()].map((w) => ({ name: w.name, x: w.x, y: w.y, dir: w.dir, pose: w.path.length ? "walk" : "stand", frame: w.frame }));
    },

    /** True while any figure has a path to follow: the loop runs only then. */
    moving() {
      return [...walkers.values()].some((w) => w.path.length > 0);
    },
  };
}
