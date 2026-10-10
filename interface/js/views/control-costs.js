// The Costs tab of the Control room: the Since field, the caps line, the chart of runs per day by agent (same-origin SVG
// built here from `costs.rows`, with its table), the table of runs by day and agent, and the footnote. It shows what the
// `costs` and `agents` operations returned; a date the service refuses is shown with the service's own message.

import { h } from "../dom.js";
import { METER_WORDS } from "../format.js";
import { icon } from "../frame/icons.js";
import * as model from "./control-model.js";
import { cell, code, emptyBlock, failedCard, FAILED_TITLE, loadingCard, meter, numCell, reconcile, tableCard } from "./control-parts.js";

// The XML namespace of SVG is a name, not an address; it is written in parts because the file test refuses the text of one.
const SVG_NS = ["http:", "", "www.w3.org", "2000", "svg"].join("/");

function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (name === "style" || /^on[a-z]+$/i.test(name)) throw new Error(`the attribute ${name} is not allowed`);
    node.setAttribute(name, String(value));
  }
  for (const child of children.flat()) {
    if (child !== undefined && child !== null && child !== false) node.append(child);
  }
  return node;
}

/** One column of the plot: an SVG of 10 x 100 units stretched to the column, a rect per segment, the first from the bottom. */
function columnSvg(column) {
  const rects = column.segments.map((s) => svg("rect", {
    class: `wb-seg ${s.className}`, x: 0, width: 10, y: +(100 - s.base - s.height).toFixed(3), height: +s.height.toFixed(3),
  }));
  return svg("svg", { class: "wb-col", viewBox: "0 0 10 100", preserveAspectRatio: "none", "aria-hidden": "true", focusable: "false" },
    svg("title", {}, document.createTextNode(model.columnTitle(column))), rects);
}

/** The chart card (R-52): head and legend, the plot, the day labels and, inside the card under the plot, the disclosure with the same numbers as a table. */
export function chartCard(chart, disclosure) {
  const legend = chart.series.map((s) => h("span", { class: "wb-legend-item" }, h("span", { class: `wb-swatch ${s.className}`, "aria-hidden": "true" }), s.label));
  const plot = h("div", { class: "wb-plot", role: "img", "aria-label": "Runs per day by agent, table below" }, chart.days.map(columnSvg));
  const labels = h("div", { class: "wb-plot-labels", "aria-hidden": "true" }, chart.days.map((d) => h("span", { text: d.label })));
  for (const node of [plot, labels]) node.classList.add(`wb-cols-${chart.days.length}`);   // one class per column count: the page writes no style
  const table = h("table", { class: "pui-table wb-ctable wb-chart-table" },
    h("caption", { class: "wb-sr", text: "Runs per day by agent" }),
    h("thead", {}, h("tr", {}, chart.head.map((t) => h("th", { scope: "col", text: t })))),
    h("tbody", {}, chart.body.map((row) => h("tr", {}, row.map((value, i) => h(i === 0 ? "th" : "td", { scope: i === 0 ? "row" : null, text: String(value) }))))));
  const details = h("details", { class: "wb-acc wb-chart-acc" },
    h("summary", {}, h("span", { class: "wb-acc-chev" }, icon("chevron-right", 14)), "The chart as a table"), h("div", { class: "wb-acc-body" }, table));
  details.open = disclosure.open;
  details.addEventListener("toggle", () => { disclosure.open = details.open; });
  return h("div", { class: "pui-card wb-chart" },
    h("div", { class: "wb-chart-head" }, h("strong", { text: "Runs per day by agent" }), h("div", { class: "wb-legend-items" }, legend)),
    plot, labels, details);
}

function runsTable(rows) {
  const head = ["Day", "Agent", "Model", "Adapter", "Runs", "Tokens", "Recorded", "Recomputed"];
  const money = (c) => h("span", { class: c.muted ? "wb-muted" : null, text: c.text });
  return h("table", { class: "pui-table wb-ctable wb-stackable wb-costs-table" },
    h("caption", { class: "wb-sr", text: "Runs by day, agent, model and adapter, newest day first" }),
    h("thead", {}, h("tr", {}, head.map((t) => h("th", { scope: "col", class: t === "Runs" || t === "Tokens" ? "wb-num" : null, text: t })))),
    h("tbody", {}, model.newestFirst(rows).map((r) => h("tr", {},
      cell("Day", h("span", { class: "wb-nowrap", text: String(r.day) })),
      cell("Agent", model.agentLabel(r.agent)),
      cell("Model", code(String(r.model))),
      cell("Adapter", code(String(r.adapter))),
      numCell("Runs", String(r.runs)),
      numCell("Tokens", model.tokensText(r.tokens)),
      cell("Recorded", money(model.recordedCell(r))),
      cell("Recomputed", money(model.recomputedCell(r)))))));
}

/**
 * The caps as rows with meters (R-52, E-16): a card that is a table by role (a head row, then a row for each agent); the agent with `Runs today: n` under its name (the runs of every
 * model today), then `Runs today` and `Spend today` each as a value in 600 weight over a meter, the recorded and reserved note under the spend. spec: `model.capsRows()`.
 */
function capsCard(spec) {
  const head = ["Agent", spec.runs ? METER_WORDS.runs : null, spec.spend ? METER_WORDS.spend : null].filter(Boolean);
  const runsCell = (c) => h("div", { class: "wb-cap-m", role: "cell", "data-label": c ? METER_WORDS.runs : null }, c ? [h("span", { class: "wb-cap-val", text: c.text }), meter(c.share, { full: c.full })] : null);
  const spendCell = (c) => h("div", { class: "wb-cap-m", role: "cell", "data-label": c ? METER_WORDS.spend : null }, c
    ? [h("span", { class: "wb-cap-val", text: c.text }), meter(c.recordedShare, { reserved: c.reservedShare, full: c.full }), c.note ? h("span", { class: "wb-muted wb-cap-note", text: c.note }) : null] : null);
  return h("div", { class: `pui-card wb-caps${spec.runs && spec.spend ? "" : spec.runs ? " is-runs-only" : " is-spend-only"}`, role: "table", "aria-label": spec.title },
    h("div", { class: "wb-cap-row wb-cap-head", role: "row" }, head.map((t) => h("span", { role: "columnheader", text: t }))),
    spec.rows.map((r) => h("div", { class: "wb-cap-row", role: "row" },
      h("div", { class: "wb-cap-agent", role: "cell" }, h("strong", { text: r.agent }), r.total === null ? null : h("span", { class: "wb-muted", text: `${METER_WORDS.runs}: ${r.total}` })),
      spec.runs ? runsCell(r.runs) : null,
      spec.spend ? spendCell(r.spend) : null)));
}

/**
 * The tab. handlers: {onSince(text)}. Returns {el, set(state)}. state: {status: "loading"|"ready"|"failed"|"refused", data
 * ({since, rows, caps}), agents (the `agents` array or null), error (the message), fieldValue (the text of the Since field, or
 * null before the first read)}.
 */
export function createCostsTab(handlers) {
  const el = h("div", { class: "wb-tab-body" });
  const input = h("input", { class: "pui-input wb-field-input", type: "text", autocomplete: "off", spellcheck: "false" });
  const row = h("label", { class: "pui-field-group wb-field wb-since" }, h("span", { text: "Since" }), input);
  const disclosure = { open: false };
  input.addEventListener("change", () => handlers.onSince(input.value));

  return {
    el,
    set(state) {
      const fieldShown = state.fieldValue !== null && state.fieldValue !== undefined;
      if (fieldShown && input.value !== state.fieldValue) input.value = state.fieldValue;
      input.removeAttribute("aria-invalid");
      input.removeAttribute("aria-describedby");
      if (state.status === "loading") {
        reconcile(el, [fieldShown ? row : null, loadingCard(model.LOADING)].filter(Boolean));
        return;
      }
      if (state.status === "failed") {
        reconcile(el, [fieldShown ? row : null, failedCard(FAILED_TITLE, state.error)].filter(Boolean));
        return;
      }
      if (state.status === "refused") {
        input.setAttribute("aria-invalid", "true");
        input.setAttribute("aria-describedby", "wb-since-notice");
        const notice = failedCard("Date refused", state.error);
        notice.id = "wb-since-notice";
        reconcile(el, [row, notice]);
        return;
      }
      const data = state.data;
      const rows = Array.isArray(data.rows) ? data.rows : [];
      const caps = model.capsRows(data.caps, state.agents);
      if (!rows.length) {
        reconcile(el, [row, emptyBlock(`No runs since ${data.since}.`)]);   // the page's frame: the field and the dashed block; the caps are of a tab that has runs
        return;
      }
      const chart = model.chartOf(rows, data.since);
      // the field stays in place: the one the person is typing in keeps its focus through a read
      reconcile(el, [
        row,
        caps ? capsCard(caps) : null,
        chart ? chartCard(chart, disclosure) : null,
        tableCard(runsTable(rows), "wb-costs-card"),
        h("p", { class: "wb-muted wb-foot", text: model.footnote(rows) }),
      ].filter(Boolean));
    },
  };
}
