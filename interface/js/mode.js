// The colour mode (R-4): one button cycles System, Light, Dark. This is the one module that sets the library's own attribute on the root
// element (`data-pui-mode="light"` or `"dark"`) or removes it (System: the system's scheme decides). Nothing is stored: the choice is the
// attribute on the root for as long as the page lives, and a reload starts on System. The library's own helper (`vendor/perfectui/js/mode.js`)
// keeps a cookie and is not loaded. Everything takes the root as an argument, so a test runs it with a stand-in.

export const ATTRIBUTE = "data-pui-mode";
export const ORDER = Object.freeze(["system", "light", "dark"]);
export const WORDS = Object.freeze({ system: "System", light: "Light", dark: "Dark" });
export const ICON_OF = Object.freeze({ system: "monitor", light: "sun", dark: "moon" });

const rootOf = () => (typeof document === "undefined" ? null : document.documentElement || null);
const listeners = new Set();

/** The mode the root element shows now: "light" or "dark" when the attribute says so, else "system". */
export function currentMode(root = rootOf()) {
  const value = root ? root.getAttribute(ATTRIBUTE) : null;
  return value === "light" || value === "dark" ? value : "system";
}

/** The mode after `mode` in the cycle System, Light, Dark; a word that is not a mode is read as System. */
export function nextMode(mode) {
  const at = Math.max(0, ORDER.indexOf(mode));
  return ORDER[(at + 1) % ORDER.length];
}

/** Put the choice on the root element: the attribute for light and dark, none for system. Returns the mode applied. */
export function applyMode(mode, root = rootOf()) {
  const chosen = ORDER.includes(mode) ? mode : "system";
  if (!root) return chosen;       // no document (a test, a worker): nothing to set
  if (chosen === "system") root.removeAttribute(ATTRIBUTE);
  else root.setAttribute(ATTRIBUTE, chosen);
  for (const fn of listeners) fn(chosen);
  return chosen;
}

/** Start on System (the page does this once, before its first draw): no attribute, the system's scheme decides. Nothing is read from a store. */
export function initMode({ root = rootOf() } = {}) {
  return applyMode("system", root);
}

/** Apply a choice. A word that is not a mode is System. Returns the mode. */
export function setMode(mode, { root = rootOf() } = {}) {
  return applyMode(mode, root);
}

/** Go to the next mode of the cycle and return it. */
export function cycleMode({ root = rootOf() } = {}) {
  return applyMode(nextMode(currentMode(root)), root);
}

/** Be told when the mode is applied (a button redraws its icon and its name). Returns the function that stops it. */
export function onMode(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
