// A value that saves itself (the caption review's face box and cover): the page does not draw a Save button for it, it saves what the person typed once the value is a
// valid one and they have stopped typing. No DOM and no network here: the view hands in three functions.
//
//   check()  -> {state: "same"}                         the fields hold what is stored (or nothing was typed): nothing to save
//               {state: "valid", value}                 a value that can be saved
//               {state: "invalid", reason}              a value that cannot: it is not sent, and the reason is shown
//   save(v)  -> Promise<{ok: true} | {ok: false, reason}>   one call to the service; a refusal is a result, never a throw
//   show(status, info)   status is "idle", "pending" (typed, waiting for a pause), "saving" (a call is out), "invalid" ({reason}) or "refused" ({reason}); info.value is the
//                        value that is pending or going out, so that it can be drawn dashed until the service has accepted it.
//
// The rules: a key press never sends (the save waits `delay` ms after the last one); leaving the field or Enter saves at once; two saves are never out together, and a
// newer valid value replaces one that has not left yet; an invalid value cancels what was pending; a refused value stays on screen, and Enter sends it again.

export const AUTOSAVE_MS = 600;

export function createAutosave({ delay = AUTOSAVE_MS, check, save, show }) {
  let timer = null;
  let next = null;           // {value}: the newest valid value, not sent yet
  let running = false;
  let stopped = false;
  let status = "idle";

  const set = (s, info = {}) => {
    status = s;
    if (!stopped) show(s, info);
  };
  const clear = () => {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  };

  async function drain() {
    if (running) return;
    running = true;
    try {
      while (next && !stopped) {
        const { value } = next;
        next = null;
        set("saving", { value });
        let result;
        try {
          result = await save(value);
        } catch (e) {
          result = { ok: false, reason: "The change was not saved." };
        }
        if (stopped) return;
        if (next) continue;            // a newer value came while this one was going: it goes now, and this answer is not shown
        const now = check();
        if (now.state === "invalid") set("invalid", { reason: now.reason });
        else if (result.ok) set("idle");
        else set("refused", { reason: result.reason || "The change was not saved.", value });
      }
    } finally {
      running = false;
    }
  }

  return {
    /** The person typed: check the fields, and wait for a pause before a valid value is sent. */
    touch() {
      const got = check();
      clear();
      if (got.state === "valid") {
        next = { value: got.value };
        set("pending", { value: got.value });
        timer = setTimeout(() => {
          timer = null;
          drain();
        }, delay);
      } else {
        next = null;
        if (got.state === "invalid") set("invalid", { reason: got.reason });
        else set("idle");
      }
    },
    /** The person left the field, or pressed Enter (`retry`): a pending value goes now; with `retry`, a refused one goes again. */
    flush({ retry = false } = {}) {
      if (timer !== null) {
        clear();
        drain();
      } else if (retry && status === "refused") {
        const got = check();
        if (got.state === "valid") {
          next = { value: got.value };
          drain();
        }
      }
    },
    /** A value that needs no pause (a tap on the frame): it goes now, over whatever was waiting. */
    submit(value) {
      clear();
      next = { value };
      set("saving", { value });
      drain();
    },
    /** An explicit action (Clear) takes over: nothing that was waiting is sent. */
    cancel() {
      clear();
      next = null;
      set("idle");
    },
    /** The view closed. */
    stop() {
      stopped = true;
      clear();
      next = null;
    },
    get status() {
      return status;
    },
  };
}
