// The colour-mode button (R-4): one control that cycles System, Light, Dark, and shows by its icon which one is chosen (a monitor, a sun, a
// moon). The frame's top row and the token prompt's bar each hold one; the choice itself lives in js/mode.js (nothing is stored).

import { h } from "../dom.js";
import { currentMode, cycleMode, ICON_OF, onMode, ORDER, WORDS } from "../mode.js";
import { icon } from "./icons.js";

/** Returns {el, destroy()}: a button that cycles the mode on a click and names the mode it shows. */
export function createModeButton() {
  const marks = ORDER.map((mode) => h("span", { class: "wb-mode-icon", "data-icon": mode }, icon(ICON_OF[mode], 16)));
  const el = h("button", { class: "pui-btn pui-surface pui-outline wb-mode-btn", type: "button", "data-mode-cycle": "" }, marks);
  function draw(mode = currentMode()) {
    el.setAttribute("data-choice", mode);
    el.setAttribute("aria-label", `Colour mode: ${WORDS[mode]}`);
    el.setAttribute("title", `Colour mode: ${WORDS[mode]}`);
  }
  el.addEventListener("click", () => {
    draw(cycleMode());
  });
  draw();
  const stop = onMode((mode) => draw(mode));     // another button (or the page) changed the mode: this one shows it
  return { el, destroy: stop };
}
