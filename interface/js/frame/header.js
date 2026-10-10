// F-1 the top row's brand (R-1) and the Back button and breadcrumbs (R-2, M-4).

import { h } from "../dom.js";
import { markImage } from "../brand.js";
import { icon } from "./icons.js";

/** The owl mark and the wordmark in one raised box at the top left (R-1). The mark names the product; the wordmark beside it is not read twice. */
export function createBrand() {
  return h("div", { class: "wb-brand" }, markImage(28), h("span", { class: "wb-wordmark", "aria-hidden": "true", text: "openhora" }));
}

/** The back button and the breadcrumb trail: in the top row right after the brand (M-4), and the bottom bar's second row on a phone (R-10). */
export function createNav() {
  const back = h("button", { class: "pui-btn pui-surface pui-outline wb-back", type: "button", "aria-label": "Back" }, icon("chevron-left", 16));
  const list = h("ol", { class: "wb-crumbs" });
  const nav = h("nav", { class: "wb-crumb-nav", "aria-label": "Breadcrumbs" }, list);
  const el = h("div", { class: "wb-nav" }, back, nav);
  let target = null;
  back.addEventListener("click", () => {
    if (target) window.location.hash = target;
  });
  return {
    el,
    /** items: [{label, href, project?}] (the last is the current one, with no href; `project` marks the crumb that names the project); backHash: where Back goes, or null (disabled). */
    set(items, backHash) {
      target = backHash;
      back.disabled = !backHash;
      list.replaceChildren(...items.map((item, i) => {
        const last = i === items.length - 1;
        // P-8: when the row is short the crumb that names the project (the middle one, or the last on the Building) is cut with an ellipsis; its whole name is its
        // text, so it is the accessible name, and the tooltip. The City and a last crumb that names a floor, the Lobby or the Control room are never cut.
        const attrs = item.project ? { title: item.label } : {};
        const label = last
          ? h("span", { class: "wb-crumb is-current", "aria-current": "page", text: item.label, ...attrs })
          : h("a", { class: "wb-crumb", href: item.href, text: item.label, ...attrs });
        return h("li", { class: item.project ? "wb-crumb-item is-project" : "wb-crumb-item" }, i > 0 ? h("span", { class: "wb-crumb-sep", "aria-hidden": "true", text: "/" }) : null, label);
      }));
    },
  };
}
