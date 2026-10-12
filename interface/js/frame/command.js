// The "terminal command" component (A-18): everywhere the page says that something is done in the terminal, it shows the exact command
// the service gave, in a code block that wraps whole, with a Copy button and the sentence of what the command does. The command is the
// service's text, verbatim: nothing here builds one. Copy uses the clipboard when the browser allows it; when it does not, the text is
// selected so that the keyboard copies it.

import { h } from "../dom.js";
import { icon } from "./icons.js";

const RUNNERS = /^(python3 |uv run |\/)/;
const BACK_AFTER_MS = 2000;

/** Whether a text of the service is a command (it starts with a runner) and not a sentence. */
export function isCommand(text) {
  return typeof text === "string" && RUNNERS.test(text.trim());
}

/**
 * Copy a text: "copied" when the clipboard took it (or the old copy command did), "selected" when the text was only selected for the
 * keyboard. env: {clipboard (an object with writeText, or null), select() (selects the text and returns whether a copy command worked)}.
 */
export async function copyCommand(text, env) {
  if (env.clipboard && typeof env.clipboard.writeText === "function") {
    try {
      await env.clipboard.writeText(text);
      return "copied";
    } catch (e) {
      // refused (no permission, an insecure context): fall through to the selection
    }
  }
  return env.select() ? "copied" : "selected";
}

/** Select the contents of a node and ask the browser to copy them: true when the old copy command worked, false when the text was only selected (for the keyboard). */
export function selectNode(node) {
  try {
    const range = document.createRange();
    range.selectNodeContents(node);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    return typeof document.execCommand === "function" ? Boolean(document.execCommand("copy")) : false;
  } catch (e) {
    return false;
  }
}

/**
 * The component. spec: {command, sentence?, label? (the Copy button's accessible name, default "Copy the command": a path says "Copy the path"), icon? (the name of an icon drawn before the word, the token prompt's "copy")}; env (for a test): {clipboard, select(), later(fn, ms)}. Returns the element, or null when there is no
 * command. Text goes in as text; a command or a sentence with markup in it is shown as it came.
 */
export function commandBlock(spec, env = null) {
  if (!spec || typeof spec.command !== "string" || !spec.command.trim()) return null;
  const code = h("code", { class: "wb-command-code", text: spec.command });
  const word = h("span", { class: "wb-copy-label", text: "Copy" });
  const button = h("button", { class: "pui-btn pui-surface pui-outline wb-copy", type: "button", "aria-label": spec.label || "Copy the command" }, spec.icon ? icon(spec.icon, 16) : null, word);
  const status = h("span", { class: "wb-copy-status wb-muted", role: "status", text: "" });
  const use = env || {
    clipboard: typeof navigator !== "undefined" && navigator.clipboard ? navigator.clipboard : null,
    select: () => selectNode(code),
    later: (fn, ms) => setTimeout(fn, ms),
  };
  if (env && !env.select) use.select = () => selectNode(code);
  button.addEventListener("click", async () => {
    const result = await copyCommand(spec.command, { clipboard: use.clipboard, select: () => use.select() });
    word.textContent = result === "copied" ? "Copied" : "Selected";
    button.classList.add("is-done");
    status.textContent = result === "copied" ? "Copied to the clipboard." : "Selected: copy it with the keyboard.";
    use.later(() => {
      word.textContent = "Copy";
      button.classList.remove("is-done");
      status.textContent = "";
    }, BACK_AFTER_MS);
  });
  const row = h("div", { class: "wb-command-row" }, code, button);
  return h("div", { class: "wb-command-block" }, spec.sentence ? h("p", { class: "wb-command-sentence", text: spec.sentence }) : null, row, status);
}
