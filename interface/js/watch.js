// The page's liveness: one small read of the service's change signal every second while the tab is visible (the numbers
// `GET /versions` answers: one per project, each growing on every write to that project's store); when a number moved, or
// after 30 quiet seconds as a safety net, the page reloads everything it shows. Nothing is asked while the tab is hidden, and
// one reload happens on return. This module holds the rule and no more: it reads and reloads through the functions it is
// given, and it keeps time through the timers it is given, so that a test drives it with a clock of its own. A poll here is a
// timeout that the visibility rule can stop, never an interval.

const EVERY_MS = 1000;       // the cadence of the signal's read
const SAFETY_MS = 30000;     // with no reload at all for this long, one full reload
const RETRY_MS = 10000;      // the read after one that failed

/**
 * A function that runs `run(reason)` one at a time. A call made while a run is in progress is not run at once: it asks for
 * one more run (with the reason of the last such call) after it, and every call made meanwhile gets the promise of that one,
 * so a caller that awaits it knows its change was read after it asked.
 */
export function coalesce(run) {
  let running = null;
  let queued = null;
  function begin(reason) {
    const mine = (async () => {
      try {
        return await run(reason);
      } finally {
        running = null;
        if (queued) {
          const next = queued;
          queued = null;
          next.resolve(begin(next.reason));
        }
      }
    })();
    running = mine;
    return mine;
  }
  function call(reason) {
    if (!running) return begin(reason);
    if (!queued) {
      queued = { reason, promise: null, resolve: null };
      queued.promise = new Promise((resolve) => { queued.resolve = resolve; });
    }
    queued.reason = reason;
    return queued.promise;
  }
  /**
   * Wait for the run that covers a change made just before: the one that is queued, else the one in progress, else a new one. A
   * view that was told to reload after a write the page's client already asked a reload for (api.onWrite) joins it, and the
   * button press makes one reload, not two.
   */
  call.join = (reason) => (queued ? queued.promise : (running || begin(reason)));
  return call;
}

/**
 * options: {read() -> Promise<string> (the signal, equal while nothing was written), reload(reason) -> Promise (false: it failed), hidden() -> boolean,
 * setTimer(fn, ms) -> id, clearTimer(id), now() -> ms, every, safety, retry}. Returns {start() -> Promise (the first read, the
 * baseline), stop(), visibilityChanged(), reloaded(key)}; `reloaded(key)` is called by the page after any reload, whatever asked for it,
 * so that the safety net counts from the last one; `key` is the signal the reload read before it read its data, which becomes the
 * baseline: a write that the reload already covers (the page's own, after it answered) is not reloaded a second time, and one that
 * came after that read is still seen by the next read.
 */
export function createWatcher(options) {
  const every = options.every ?? EVERY_MS;
  const safety = options.safety ?? SAFETY_MS;
  const retry = options.retry ?? RETRY_MS;
  let timer = null;
  let baseline = null;
  let stopped = true;
  let failed = false;
  let lastReload = 0;
  let generation = 0;

  function clear() {
    if (timer !== null) options.clearTimer(timer);
    timer = null;
  }

  function schedule(ms) {
    clear();
    if (stopped || options.hidden()) return;
    timer = options.setTimer(() => { timer = null; tick(); }, ms);
  }

  /** Ask for a reload. One that answers `false` (a refusal that is not a lost connection: the page says so) is a failure, read again after 10 s. */
  async function trigger(reason) {
    lastReload = options.now();
    try {
      if ((await options.reload(reason)) === false) failed = true;
    } catch (e) {
      // the page says what failed; the watcher goes on
    }
  }

  async function tick() {
    const mine = generation;
    let key;
    try {
      key = await options.read();
    } catch (e) {
      if (mine !== generation) return;
      if (e && e.unauthorized) {          // the client already sent the page back to the token prompt
        stop();
        return;
      }
      if (!failed) {
        failed = true;
        await trigger("unreachable");     // once: the page shows that the service did not answer
      }
      if (mine === generation) schedule(retry);
      return;
    }
    if (mine !== generation) return;
    let reason = null;
    if (failed) reason = "recovered";
    else if (baseline !== null && key !== baseline) reason = "change";
    else if (options.now() - lastReload >= safety) reason = "safety";
    failed = false;
    baseline = key;
    if (reason) await trigger(reason);
    if (mine === generation) schedule(failed ? retry : every);
  }

  /** On return to a visible tab: take the signal as the new baseline, then reload once, whatever moved while hidden. */
  async function comeBack() {
    const mine = generation;
    try {
      baseline = await options.read();
      failed = false;
    } catch (e) {
      if (mine !== generation) return;
      if (e && e.unauthorized) {
        stop();
        return;
      }
      failed = true;
    }
    if (mine !== generation) return;
    await trigger("return");
    if (mine === generation) schedule(failed ? retry : every);
  }

  function stop() {
    stopped = true;
    generation += 1;
    clear();
  }

  return {
    start() {
      stopped = false;
      failed = false;
      baseline = null;
      generation += 1;
      lastReload = options.now();
      clear();
      if (options.hidden()) return Promise.resolve();
      return tick();
    },
    stop,
    visibilityChanged() {
      if (stopped) return;
      generation += 1;
      clear();
      if (!options.hidden()) comeBack();
    },
    reloaded(key) {
      lastReload = options.now();
      if (key !== undefined && key !== null) baseline = key;
    },
  };
}
