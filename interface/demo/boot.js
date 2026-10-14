// The demo's start, loaded before js/main.js by the built copy of the page: a token held in memory (so the token prompt never shows), a ribbon
// that says this is the demo, the autopilot and the bridge to the page that frames it. The visitor's own input (a press, the wheel, a key,
// a touch) stops the autopilot: from then on the page answers the visitor from the world as it stands.

import { h } from "../js/dom.js";
import { setToken } from "../js/token.js";
import { createBridge } from "./bridge.js";
import { createAutopilot, STEPS } from "./scenario.js";
import { world } from "./instance.js";

// A string of the shape of the service's token (32 to 512 printable characters). It opens nothing: the demo has no service.
const DEMO_TOKEN = "demo-token-not-a-secret-fictional-0000";   // security-scan: allow secret-assignment -- a fictional string of the right shape; the demo has no service to open
const TAKE_OVER_EVENTS = ["pointerdown", "wheel", "keydown", "touchstart"];
const reduced = Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

setToken(DEMO_TOKEN);

function find(action) {
  const all = Array.from(document.querySelectorAll(action.selector));
  const shown = action.label ? all.filter((el) => (el.textContent || "").trim().startsWith(action.label)) : all;
  return shown.find((el) => !el.disabled && el.getClientRects().length) || null;
}

/** What a person does on the page, done through the page's own controls; false when the control is not there (the story then makes the change itself). */
function perform(action) {
  const el = find(action);
  if (!el) return false;
  if (action.do === "type") {
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value");
    if (setter && setter.set) setter.set.call(el, action.text);
    else el.value = action.text;
    el.dispatchEvent(new Event("input", { bubbles: true }));
  } else if (action.do === "submit") {
    if (typeof el.requestSubmit === "function") el.requestSubmit();
    else el.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  } else if (action.do === "click") {
    el.click();
  } else {
    return false;
  }
  return true;
}

const autopilot = createAutopilot({
  world,
  setRoute: (hash) => { if (window.location.hash !== hash) window.location.hash = hash; },
  perform,
  schedule: (fn, ms) => window.setTimeout(fn, ms),
  cancel: (id) => window.clearTimeout(id),
  post: (message) => bridge.post(message),
  reduced,
});
const bridge = createBridge({ win: window, parent: window.parent, origin: window.location.origin, autopilot });

function ribbon() {
  const start = h("button", { class: "pui-btn pui-surface pui-outline wb-touch", type: "button", text: "Start over" });
  start.addEventListener("click", () => { autopilot.replay(); });
  const parts = [h("span", { class: "pui-badge pui-soft pui-warn", text: "Demo · fictional data" })];
  if (reduced) {
    const next = h("button", { class: "pui-btn pui-surface pui-outline wb-touch", type: "button", text: "Next step" });
    next.addEventListener("click", () => { autopilot.play(); });
    parts.push(next);
  }
  parts.push(start);
  return h("div", { class: "wb-demo-ribbon", role: "note", "aria-label": "This is a demo with fictional data" }, parts);
}

function drawn() {
  const app = document.getElementById("app");
  return Boolean(app && app.firstElementChild && !app.querySelector(".tk-root"));
}

function begin() {
  document.body.prepend(ribbon());
  for (const type of TAKE_OVER_EVENTS) {
    window.addEventListener(type, (event) => {
      if (!event.isTrusted) return;    // the autopilot's own clicks and keystrokes are not the visitor's
      if (autopilot.takeOver()) bridge.post({ type: "took-over", step: autopilot.index, id: STEPS[autopilot.index].id });
    }, { capture: true, passive: true });
  }
  const waiting = window.setInterval(() => {
    if (!drawn()) return;
    window.clearInterval(waiting);
    bridge.post({ type: "ready", steps: STEPS.length });
    if (!reduced && !bridge.heard && autopilot.status === "idle") autopilot.play();
  }, 100);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", begin);
else begin();
