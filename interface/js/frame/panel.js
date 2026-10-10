// F-7 the panel shell: a card at the right of the scene (a section of the page on a phone) with a header (a tinted tile, a
// title and a line under it) and a body. A screen fills the body.

import { h } from "../dom.js";
import { bindDrawer, createGrip } from "./drawer.js";
import { icon } from "./icons.js";

let counter = 0;

/**
 * A panel for a screen. spec: {screen, title, subtitle, icon, tone, width}. On a phone the panel is a bottom sheet (frame/drawer.js): its
 * handle is the first child and the header starts a drag. Returns {el, body, sub, drawer}; `sub` is the line under the title, which a screen may rewrite (the Control room's follows its tab);
 * the screen calls `drawer.destroy()` before it removes the panel.
 */
export function createPanel(spec) {
  counter += 1;
  const titleId = `wb-panel-title-${counter}`;
  const body = h("div", { class: "wb-panel-body" });
  const sub = h("span", { class: "wb-panel-sub", text: spec.subtitle || "" });
  const grip = createGrip();
  const el = h("section", { class: `pui-card wb-panel wb-drawer wb-panel-${spec.width || "narrow"}`, role: "region", "aria-labelledby": titleId, id: "wb-panel", tabindex: "-1" },
    grip,
    h("div", { class: "wb-panel-head" },
      h("span", { class: `wb-tile pui-soft pui-${spec.tone || "theme"}` }, icon(spec.icon || "building-2", 18)),
      h("div", { class: "wb-panel-titles" }, h("strong", { class: "wb-panel-title", id: titleId, text: spec.title }),
        sub)),
    body);
  const drawer = bindDrawer(el, { screen: spec.screen, grip });
  return { el, body, sub, drawer };
}
