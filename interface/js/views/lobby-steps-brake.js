// The brake of the step tasks (P5c), a section of the Building's panel. The runtime's own pseudo-agent has two modes, `autonomous` and `stopped`; the `agents` read
// carries its mode as `steps` ({agent: "runtime", mode}), and `POST /projects/{p}/agents/runtime/mode` sets it. While it is stopped the dispatcher starts no step
// task (a task started by hand from the terminal still runs). The section is a state line and one button: "Stop step tasks" (a narrowing, which the page's policy
// never withholds: `set-mode:down`) or "Resume step tasks" (`set-mode:up`, the policy's; without it a line names the terminal command). It sends exactly one request
// per click through the client it is given, shows a refusal in the service's words, and is drawn only when the read carried a brake. It lives with the Lobby's modules
// because a write may not be sent from the Building itself (test_interface_files.py); the Building only places it.

import { h } from "../dom.js";
import { can as pageMay } from "../permissions.js";

export const HEAD = "Step tasks";
export const ON = "Step tasks of a kind that may run on its own start on their own.";
export const OFF = "Step tasks are stopped: the dispatcher starts none. A task you start yourself from the terminal still runs.";
export const RESUME_NOTE = "Resuming is set in the terminal: set-mode --agent runtime --mode autonomous.";

/**
 * env: {api (the client: setMode), project (id), project entry getter `entry()` (the GET /projects entry, for the policy), refresh()}. Returns {el, update(detail, shown)};
 * detail is the project's entry of the snapshot (`steps` among its fields), shown whether the panel may draw the section at all.
 */
export function createStepsBrake(env) {
  const head = h("h3", { class: "wb-steps-head", text: HEAD });
  const line = h("p", { class: "wb-steps-line" });
  const button = h("button", { class: "pui-btn pui-surface pui-outline wb-steps-btn", type: "button", "data-key": "steps-brake" });
  const note = h("p", { class: "wb-steps-note", hidden: true });
  const error = h("div", { class: "wb-form-error" });
  const el = h("section", { class: "wb-steps-sec", hidden: true }, head, line, button, note, error);
  let mode = "autonomous";
  let sending = false;
  let last = { detail: null, shown: false };

  const may = (kind) => pageMay(env.entry ? env.entry() : null, "set-mode", kind);

  function draw() {
    const { detail, shown } = last;
    const found = detail && detail.steps && typeof detail.steps.mode === "string" ? detail.steps.mode : null;
    el.hidden = !(shown && found);
    if (el.hidden) return;
    mode = found === "stopped" ? "stopped" : "autonomous";
    const resume = mode === "stopped";
    const allowed = may(resume ? "up" : "down");
    line.textContent = resume ? OFF : ON;
    button.hidden = !allowed;
    button.disabled = sending;
    button.textContent = resume ? "Resume step tasks" : "Stop step tasks";
    note.hidden = !(resume && !allowed);
    note.textContent = resume && !allowed ? RESUME_NOTE : "";
  }

  button.addEventListener("click", async () => {
    if (sending) return;
    sending = true;
    button.disabled = true;
    error.replaceChildren();
    try {
      await env.api.setMode(env.project, "runtime", mode === "stopped" ? "autonomous" : "stopped");
      if (env.refresh) await env.refresh();
    } catch (e) {
      error.replaceChildren(h("p", { class: "notice pui-soft pui-error wb-notice-card", role: "alert", text: e && e.message ? e.message : "The change was refused." }));
    }
    sending = false;
    draw();
  });

  return { el, update(detail, shown) { last = { detail, shown }; draw(); } };
}
