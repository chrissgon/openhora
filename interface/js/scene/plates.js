// The HTML of the Building's floor plates and of the other labels the building and room scenes add (round 4: building.html), and the pure
// arithmetic that stacks the plates in a column without overlap. A plate (R-25) is one size: a name row (the state dot, the name, the decisions
// badge, the mode word, the state as a soft badge, R-26) and the two meters of the day side by side; with more than eight floors (`is-short`), or when the
// column would not fit the free height (`is-tiny`, which `labels.js` adds and takes off), the name row alone. No count chips, no pips. Every fact on a plate is also in the floors list (a row, `rowNode`):
// the plates are `aria-hidden`. The phone's floor card (`floorCardNode`) stands in the corner of the scene. The work-order tag (R-29) is a badge.

import { h } from "../dom.js";
import { icon } from "../frame/icons.js";
import { METER_TIPS, costNote } from "../format.js";

/** The mode's pips: four 5 px squares, as many filled as the mode counts (the Floor's header and Agent tab still draw them). */
export function pips(count) {
  const node = h("span", { class: "wb-pips", "aria-hidden": "true" });
  for (let i = 0; i < 4; i++) node.append(h("span", { class: `wb-pip${i < count ? " is-on" : ""}` }));
  return node;
}

/**
 * A meter's track: the fill in the theme colour for `share` and, when something is reserved (`reservedShare` above zero), a second segment in the
 * reserved tint right after it, on the same line (A-20). Every meter of the page is made by this.
 */
export function trackNode(share, full, reservedShare = 0, extraClass = "") {
  const fill = h("span", { class: `wb-meter-fill${full ? " is-full" : ""}` });
  fill.style.setProperty("--wb-share", `${Math.round(share * 100)}%`);
  const track = h("span", { class: `wb-meter${reservedShare > 0 ? " has-reserved" : ""}${extraClass ? ` ${extraClass}` : ""}`, "aria-hidden": "true" }, fill);
  if (reservedShare > 0) {
    const reserved = h("span", { class: "wb-meter-reserved" });
    reserved.style.setProperty("--wb-share", `${Math.round(reservedShare * 100)}%`);
    track.append(reserved);
  }
  return track;
}

/**
 * The chips of a plate (A-12), in this order and each only when its count is not zero: done, running, queued, left (planned or blocked); then, when a
 * planned task waits for another (A-29), one more chip, "waiting for #10" (or "2 waiting"), whose tooltip holds each reason. The waiting tasks are counted in "left".
 */
export function chipNodes(p) {
  const chips = [["done", p.done, "pui-success"], ["running", p.running, "pui-theme"], ["queued", p.queued, "pui-muted"], ["left", p.left, "pui-muted"]];
  const nodes = chips.filter(([, count]) => count > 0).map(([word, count, tone]) => h("span", { class: `pui-badge ${tone} pui-soft pui-rounded-full`, text: `${count} ${word}` }));
  if (p.waits && p.waits.text) nodes.push(h("span", { class: "pui-badge pui-muted pui-outline pui-rounded-full wb-chip-waiting", title: p.waits.title || null, text: p.waits.text }));
  return nodes;
}

/** The state badge of a plate, a row and the phone's card (R-26): a soft badge in the state's tone, ellipsised with its whole text as the tooltip. */
function stateBadge(text, tone) {
  return h("span", { class: `pui-badge pui-soft ${tone || "pui-muted"} wb-st`, title: text, text });
}

/** "3 / 6" as a bold figure over the cap: `<strong>3</strong> / 6`, then the word when there is one. */
function figure(text, word) {
  const [value, ...cap] = String(text).split(" / ");
  return h("span", {}, h("strong", { text: value }), cap.length ? ` / ${cap.join(" / ")}` : "", word ? h("span", { class: "wb-muted", text: ` ${word}` }) : null);
}

function plateMeter(tip, text, word, share, full, reservedShare = 0) {
  return h("div", { class: "wb-plate-meter", title: tip || null }, figure(text, word), trackNode(share, full, reservedShare));
}

/**
 * A floor plate (R-25, R-26). p: {name, label, dot, decisions, word, tone, modeLine, actingLine, runsText, runsShare, usdText, usdShare, inUse: {runs, spend}, mode,
 * usdRecordedShare, usdReservedShare, usdNote, usdReserved, unknown, selected, off, tiny}. One size: the name row and the two meters (a meter only for a cap in use,
 * A-38) side by side, with `title` the sentence of what each counts; `tiny` (more than eight floors) is the name row alone. The plate is the scene's label and a
 * pointer target (hover marks the floor in three places, R-28, `is-hover`).
 */
export function plateNode(p, attrs = {}, tag = "div") {
  const row1 = h("div", { class: "wb-plate-row" },
    h("span", { class: `wb-dot is-${p.dot}` }),
    h("strong", { class: "wb-plate-name", text: p.label }),
    p.decisions > 0 ? h("span", { class: "pui-badge pui-warn pui-soft pui-rounded-full", "aria-label": `${p.decisions} decision${p.decisions === 1 ? "" : "s"} waiting`, text: String(p.decisions) }) : null,
    p.mode ? h("span", { class: "wb-plate-mode", title: [p.modeLine, p.actingLine].filter(Boolean).join("; ") || null, text: p.mode }) : null,
    h("span", { class: "wb-plate-state" }, stateBadge(p.word, p.tone)));
  const use = p.inUse || { runs: true, spend: true };      // A-38: a meter only for a cap in use
  const spendTip = [METER_TIPS.spend, costNote(p.usdNote, p.usdReserved, p.unknown)].filter(Boolean).join(" ");
  const meters = p.tiny ? null : h("div", { class: "wb-plate-meters" },
    use.runs ? plateMeter(METER_TIPS.runs, p.runsText, "runs", p.runsShare, p.runsShare >= 1) : null,
    use.spend ? plateMeter(spendTip, p.usdText, "", p.usdRecordedShare !== undefined ? p.usdRecordedShare : p.usdShare, p.usdShare >= 1, p.usdReservedShare || 0) : null);
  const klass = `wb-plate${p.off ? " is-off" : ""}${p.tiny ? " is-short" : ""}${attrs.class ? ` ${attrs.class}` : ""}`;
  return h(tag, { ...attrs, class: klass, "data-floor": p.name }, row1, meters);
}

/**
 * A row of the floors list (R-27): the name, the decisions badge and the mode word on one line with the state badge at the right, the count chips under it when
 * there are any (and "acting as <mode>" when it differs), the chevron. `attrs`: {href, aria-label, class}. The same facts as the plate, the chips and the meters' words
 * in the row's accessible name (the plate is hidden from a screen reader).
 */
export function rowNode(p, attrs = {}) {
  const chips = [...chipNodes(p), ...(p.actingLine ? [h("span", { class: "pui-badge pui-muted pui-outline pui-rounded-full wb-acting", text: p.actingLine })] : [])];
  return h("a", { ...attrs, class: `wb-fl-row${p.off ? " is-off" : ""}${attrs.class ? ` ${attrs.class}` : ""}`, "data-floor": p.name },
    h("span", { class: `wb-dot is-${p.dot}` }),
    h("span", { class: "wb-fl-title" },
      h("strong", { class: "wb-fl-name", text: p.label }),
      p.decisions > 0 ? h("span", { class: "pui-badge pui-warn pui-soft pui-rounded-full", "aria-label": `${p.decisions} decision${p.decisions === 1 ? "" : "s"} waiting`, text: String(p.decisions) }) : null,
      p.mode ? h("span", { class: "wb-fl-mode", title: p.modeLine || null, text: p.mode }) : null),
    h("span", { class: "wb-fl-state" }, stateBadge(p.word, p.tone)),
    chips.length ? h("span", { class: "wb-fl-chips" }, chips) : null,
    h("span", { class: "wb-fl-chev" }, icon("chevron-right", 14)));
}

/**
 * The phone's floor card (R-26, building.html at 375 px): the name row (dot, name, decisions badge, the state as a soft badge) and one line: the mode word, the runs and
 * the spend. c: cardOf(row). Hangs at the bottom left of the scene above the camera buttons; the page's rows are `rowNode`, not this.
 */
export function floorCardNode(c, attrs = {}, tag = "div") {
  const head = h("span", { class: "wb-fc-head" },
    h("span", { class: `wb-dot is-${c.dot}` }),
    h("strong", { class: "wb-fc-name", text: c.label }),
    c.decisions > 0 ? h("span", { class: "pui-badge pui-warn pui-soft pui-rounded-full", text: String(c.decisions) }) : null,
    h("span", { class: "wb-fc-state" }, stateBadge(c.word, c.tone)));
  const line = c.mode || c.runsLine
    ? h("span", { class: "wb-fc-runs", title: c.runsNote || null }, c.mode ? h("span", { class: "wb-fc-mode", title: c.modeLine || null, text: c.mode }) : null, c.mode && c.runsLine ? " · " : "", c.runsLine || "")
    : null;
  const klass = `wb-floor-card${c.off ? " is-off" : ""}${attrs.class ? ` ${attrs.class}` : ""}`;
  return h(tag, { ...attrs, class: klass, "data-floor": c.name }, head, line);
}

/** The work-order tag's label (R-29): the request's number, `#7`, as a badge in the brand colour at the left corner of its floor. */
export function tagNode(spec) {
  const number = String(spec.text || "").replace(/^#/, "");
  return h("span", { class: "wb-label wb-tag pui-badge pui-theme pui-solid", title: number ? `Request ${number} is on this floor` : null, text: spec.text });
}

/**
 * The wall board's label (R-32, floor.html): over the room's board of notes, the state dot and the title (`#52 Implement the change · current task`), then the mono lines: the skill, the
 * state and `for 12 min`, then the run. It is HTML over the scene, not drawn in it, and not a click target.
 */
export function boardNode(spec) {
  return h("div", { class: "wb-label wb-label-board wb-wallboard" },
    h("div", { class: "wb-fp-row wb-label-row" }, h("span", { class: `wb-dot is-${spec.dot}` }), h("strong", { class: "wb-fp-name wb-label-name", text: spec.title })),
    ...spec.lines.map((line) => h("span", { class: "mono wb-wb-line wb-label-sub", text: line })));
}

/** The door's label in the Lobby (A-59, M-17): text alone, fitted on the plaque of the door (labels.js `placeLabels` writes its matrix); the plate in the scene is its ground, so it has no badge, border or shadow. */
export function doorNode(spec) {
  return h("div", { class: "wb-label wb-label-fit" }, h("span", { class: "wb-door-tag", text: spec.text }));
}

/**
 * Stack boxes in one column with no overlap. items: [{want, height}] (want is the wished centre, in pixels, from the
 * floor's own height on screen); the result is the centre of each, in the same order, kept inside [top, bottom] with
 * `gap` between neighbours. Order follows `want`. When the column cannot fit, `fits` is false and the result is still the
 * tightest packing from the top (the caller then shortens the plates to the name row alone).
 */
export function stackColumn(items, top, bottom, gap) {
  const order = items.map((item, index) => ({ ...item, index })).sort((a, b) => a.want - b.want || a.index - b.index);
  const total = order.reduce((sum, item) => sum + item.height, 0) + gap * Math.max(0, order.length - 1);
  const room = bottom - top;
  const fits = total <= room;
  const tops = order.map((item) => item.want - item.height / 2);
  // push down so none overlaps the one above, then pull up so none passes the bottom
  for (let i = 0; i < order.length; i++) {
    const min = i === 0 ? top : tops[i - 1] + order[i - 1].height + gap;
    if (tops[i] < min) tops[i] = min;
  }
  if (fits) {
    for (let i = order.length - 1; i >= 0; i--) {
      const max = i === order.length - 1 ? bottom - order[i].height : tops[i + 1] - gap - order[i].height;
      if (tops[i] > max) tops[i] = max;
    }
  }
  const centres = new Array(items.length);
  order.forEach((item, i) => { centres[item.index] = tops[i] + item.height / 2; });
  return { centres, fits };
}
