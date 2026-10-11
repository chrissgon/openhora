// The bridge to the page that frames the demo: commands in, events out, by postMessage. A message is accepted only when it comes from the
// same origin as the demo and from the window that frames it (`event.origin === location.origin`, `event.source === window.parent`);
// anything else is ignored without a word. In: {type: "play" | "pause" | "replay" | "goto", step}. Out: {type: "ready" | "step" |
// "took-over" | "ended", step, id} (a step also carries its caption key, and ready the number of steps).

export const COMMANDS = Object.freeze(["play", "pause", "replay", "goto"]);

/** The command a message event carries, or null: from another origin, from another window, or not a command of the list. */
export function commandOf(event, origin, parent) {
  if (!origin || origin === "null") return null;      // a page with an opaque origin shares it with every other: it hears nobody
  if (!event || event.origin !== origin || event.source !== parent) return null;
  const data = event.data;
  if (!data || typeof data !== "object" || typeof data.type !== "string" || !COMMANDS.includes(data.type)) return null;
  if (data.type === "goto" && !Number.isInteger(data.step)) return null;
  return { type: data.type, step: Number.isInteger(data.step) ? data.step : undefined };
}

/**
 * options: {win (the demo's window), parent (the window that frames it), origin, autopilot}. Returns {post(message), dispose()}; `post` sends an
 * event to the parent, to the demo's own origin only, and sends nothing when the demo is not framed.
 */
export function createBridge({ win, parent, origin, autopilot }) {
  let heard = false;      // the framing page has given a command: the demo does not start by itself over it
  function post(message) {
    if (!parent || parent === win || !origin || origin === "null") return;
    try {
      parent.postMessage(message, origin);
    } catch (e) {
      // the frame's window went away: nothing to tell
    }
  }
  function onMessage(event) {
    const command = commandOf(event, origin, parent);
    if (!command) return;
    heard = true;
    if (command.type === "play") autopilot.play();
    else if (command.type === "pause") autopilot.pause();
    else if (command.type === "replay") autopilot.replay();
    else if (command.type === "goto") autopilot.goto(command.step);
  }
  win.addEventListener("message", onMessage);
  return { post, get heard() { return heard; }, dispose: () => win.removeEventListener("message", onMessage) };
}
