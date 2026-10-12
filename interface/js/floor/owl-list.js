// The HTML twin of a room's owls (PAR-7e, SPEC-PAR-7 section 12): one focusable link for each owl, in seat order, with the words of the owl's tooltip, that goes where a click on the owl goes.
// It is clipped until something in it has the focus (floor.css), as the City's list of projects is. The focus or the pointer on a link brackets that owl in the scene
// (`highlight(id, source)` of the engine), as the focus on a floor's row brackets the floor in the Building. Every word is text.

import { fill, h } from "../dom.js";

/**
 * hashOf(target) -> the hash a target opens; highlight(id, source) -> brackets the owl with that pick id in the scene ("keyboard" or "pointer"; null clears it).
 * Returns {el, update(targets)}: targets are the world model's `room.owls` ([{seat, id, tip, route}]); with none the list is hidden.
 */
export function createOwlList({ hashOf, highlight }) {
  const list = h("ul", { class: "wb-owl-list" });
  const el = h("section", { class: "wb-owls", "aria-label": "Owls of this floor" }, list);
  el.hidden = true;
  let shown = "";

  function row(target) {
    const link = h("a", { class: "wb-owl-link", href: hashOf(target), "data-key": target.id, text: target.tip });
    link.addEventListener("focus", () => highlight(target.id, "keyboard"));
    link.addEventListener("blur", () => highlight(null, "keyboard"));
    link.addEventListener("pointerenter", () => highlight(target.id));
    link.addEventListener("pointerleave", () => highlight(null));
    return h("li", { class: "wb-owl-item" }, link);
  }

  return {
    el,
    update(targets) {
      const rows = Array.isArray(targets) ? [...targets].sort((a, b) => a.seat - b.seat) : [];
      const key = JSON.stringify(rows.map((t) => [t.seat, t.id, t.tip, hashOf(t)]));
      if (key === shown) return;
      shown = key;
      const active = document.activeElement;
      const kept = active && el.contains(active) && active.getAttribute ? active.getAttribute("data-key") : null;
      fill(list, rows.map(row));
      el.hidden = rows.length === 0;
      if (!kept) return;
      const next = [...list.querySelectorAll("a")].find((n) => n.getAttribute("data-key") === kept);
      if (next && next.focus) next.focus({ preventScroll: true });
    },
  };
}
