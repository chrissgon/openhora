// The render scheduler: the state machine that decides when a frame is drawn. It imports nothing and touches no
// document, so a test can run it with a fake clock. The rules (handoff scene.md section 7):
//   - a frame is drawn only when something asked for one (requestRender: data, camera, hover, focus or size changed) or
//     while an animation runs; there is no standing requestAnimationFrame loop: the loop starts for the work and stops
//     when it is done;
//   - an ambient animation (the beacon) is drawn at most AMBIENT_FPS times a second; a transition (the camera, a
//     marker dropping in) is drawn on every browser frame while it lasts;
//   - while the document is hidden nothing is scheduled and nothing is drawn; on becoming visible one frame is drawn;
//   - with reduced motion an ambient animation is never started (the frame it would have drawn is still asked for once).

export const AMBIENT_FPS = 30;

/**
 * deps: raf(fn) -> handle, caf(handle), render(timestamp), hidden() -> boolean (the initial state), reduced() -> boolean.
 * Returns {requestRender, start, stop, setHidden, isRunning, stats, dispose}.
 */
export function createLoop({ raf, caf, render, hidden = () => false, reduced = () => false }) {
  const animations = new Map();   // name -> {ambient}
  let dirty = false;
  let handle = null;
  let last = -Infinity;
  let isHidden = Boolean(hidden());
  let renders = 0;
  let disposed = false;
  const interval = 1000 / AMBIENT_FPS;

  function wanted() {
    return dirty || animations.size > 0;
  }

  function schedule() {
    if (disposed || handle !== null || isHidden || !wanted()) return;
    handle = raf(tick);
  }

  function tick(timestamp) {
    handle = null;
    if (disposed || isHidden) return;
    let draw = false;
    if (animations.size === 0) {
      draw = dirty;
    } else {
      const transition = [...animations.values()].some((a) => !a.ambient);
      draw = transition || timestamp - last >= interval - 1;
    }
    if (draw) {
      dirty = false;
      last = timestamp;
      renders += 1;
      render(timestamp);
    }
    schedule();
  }

  return {
    /** Something changed: draw one frame at the next browser frame. */
    requestRender() {
      dirty = true;
      schedule();
    },
    /** Start an animation by name; `ambient` ones are held to AMBIENT_FPS and are not started with reduced motion. */
    start(name, { ambient = false } = {}) {
      if (ambient && reduced()) {
        this.requestRender();
        return false;
      }
      animations.set(name, { ambient });
      dirty = true;
      schedule();
      return true;
    },
    /** An animation ended. One last frame is drawn (its final state). */
    stop(name) {
      if (animations.delete(name)) {
        dirty = true;
        schedule();
      }
    },
    /** The document became hidden or visible. */
    setHidden(value) {
      isHidden = Boolean(value);
      if (isHidden) {
        if (handle !== null) caf(handle);
        handle = null;
      } else {
        dirty = true;
        schedule();
      }
    },
    isRunning() {
      return animations.size > 0;
    },
    /** True while the animation `name` is started and not stopped. */
    isActive(name) {
      return animations.has(name);
    },
    stats() {
      return { renders, scheduled: handle !== null, animations: animations.size, hidden: isHidden };
    },
    dispose() {
      disposed = true;
      if (handle !== null) caf(handle);
      handle = null;
      animations.clear();
    },
  };
}
