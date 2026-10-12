// What a file handed to a task needs before it is sent: the refusal the page can know (over 25 MiB, a name the service would refuse), the
// base64 of its bytes, and the second step of a hand-over (C-17): the name of the file chosen and the button that sends it. Choosing a file
// sends nothing. The Agent tab's "Hand a file over" and the review card's use them; the service checks both again.

import { h } from "../dom.js";

export const MAX_FILE_BYTES = 25 * 1024 * 1024;
const NAME = /^[A-Za-z0-9._-]{1,100}$/;

/** The base64 of some bytes (the body of a file handed over): chunked so a large file does not overflow the call stack. */
export function toBase64(bytes) {
  let text = "";
  for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(text);
}

/**
 * The chooser of "Hand a file over" (floor.html: a dashed box): the heading, the line of a web task when there is one, the button `Choose a file` that opens the file input, the input itself
 * (drawn out of sight: the button is what the person sees, the input is what a screen reader and a test reach, named like the heading) and the hint. Returns {nodes, button}: `nodes` go in the
 * box in this order, `button` is the one to disable with the input.
 */
let chooserCount = 0;

export function handChooser({ input, line, hint }) {
  const button = h("button", { class: "pui-btn pui-surface pui-outline wb-small-button wb-hand-choose", type: "button", text: "Choose a file" });
  button.addEventListener("click", () => { if (!input.disabled) input.click(); });
  input.setAttribute("aria-label", "Hand a file over");
  chooserCount += 1;      // the hint and the line of a web task describe the file input
  const ids = [];
  for (const [node, name] of [[line, "line"], [hint, "hint"]]) {
    if (!node) continue;
    node.setAttribute("id", `wb-hand-${name}-${chooserCount}`);
    ids.push(node.getAttribute("id"));
  }
  if (ids.length) input.setAttribute("aria-describedby", ids.join(" "));
  input.setAttribute("tabindex", "-1");
  return { nodes: [h("span", { class: "wb-sec-head wb-field-label", text: "Hand a file over" }), line, h("div", { class: "wb-hand-row" }, button), input, hint], button };
}

/**
 * The second step of a hand-over: the chosen file's name and the button "Hand over to task #n" that sends it, or null while no file is chosen.
 * `onSend` is called by the button; `disabled` is true while a send runs or the control is locked.
 */
export function handOverStep(file, taskId, onSend, { disabled = false } = {}) {
  if (!file) return null;
  const label = `Hand over to task #${taskId}`;
  const button = h("button", { class: "pui-btn pui-surface pui-outline wb-hand-send wb-hand-button", type: "button", "aria-label": label, disabled, text: label });
  button.addEventListener("click", onSend);
  return h("div", { class: "wb-hand-step" }, h("span", { class: "mono wb-hand-name wb-hand-chosen", text: file.name }), button);
}

/** The refusal before sending, or "" when the file may be sent: over 25 MiB, or a name the service would refuse. */
export function fileRefusal(name, size) {
  if (size > MAX_FILE_BYTES) return "A file handed to a task is at most 25 MiB.";
  if (!NAME.test(name)) return "The file name may hold letters, digits, ., _ and -, at most 100 characters.";
  return "";
}
