// The Skills tab of the Control room (control-room.html, R-53, R-54, R-55): the checks notice (when a check failed), the legend, the filters, the list of skills as
// accordions in five columns (a card per skill on a phone) and, in an open row, the manifest, the runs here and the two sentences. It shows what the `skills` operation
// returned: the band is its word, the score its number, and in a tier the score comes first and the band's chip after it (M-2). The filters only narrow the rows on the page.

import { h } from "../dom.js";
import { PHONE_QUERY } from "../frame/drawer.js";
import { icon } from "../frame/icons.js";
import * as model from "./control-model.js";
import { chip, code, emptyBlock, failedCard, FAILED_TITLE, loadingCard, noticeCard, reconcile } from "./control-parts.js";

const CAPTION = "Skills in scope, with their band and score on the reference model and the floor model";

/** A tier's band: the score first, then the band's chip (R-53), or a dash when the operation sent no pair for the tier. */
function bandNode(skill, tier) {
  const found = model.chipOf(skill, tier);
  if (!found) return h("span", { class: "wb-muted", text: "-" });
  return h("span", { class: "wb-band" }, h("span", { class: "wb-score", text: found.score }), chip(found.className, found.band));
}

/** What a screen reader hears for a row (the head row is hidden from it): the name, the version, the area and the two tiers. */
function rowName(skill) {
  const said = (tier, column) => {
    const found = model.chipOf(skill, tier);
    return found ? `${column} ${found.score} ${found.band}` : `${column}: none`;
  };
  return `${skill.name}, version ${skill.version}, ${skill.area}, ${said("strong", "reference model")}, ${said("floor", "floor model")}`;
}

/** The tab. Returns {el, set(state), dispose()}; state: {status: "loading"|"ready"|"failed", data, error}. */
export function createSkillsTab() {
  const el = h("div", { class: "wb-tab-body" });
  const ui = { area: "", band: "", name: "", open: new Set() };
  let skills = [];
  let filters = null;     // built once, so that typing in the search field keeps its focus
  let results = null;
  let peers = new Map();  // a skill's name -> its row of the list and its card (one is on show, by width): they open together
  const phone = window.matchMedia(PHONE_QUERY);
  const onPhone = () => { if (filters) filters.box.open = !phone.matches; };
  phone.addEventListener("change", onPhone);

  function buildFilters() {
    const area = h("select", { class: "pui-input wb-select" });
    const band = h("select", { class: "pui-input wb-select" },
      h("option", { value: "", text: "All bands" }), model.BANDS.map((b) => h("option", { value: b, text: b })));
    const name = h("input", { class: "pui-input wb-field-input", type: "text", autocomplete: "off", spellcheck: "false" });
    const group = (label, control) => h("label", { class: "pui-field-group wb-field" }, h("span", { text: label }), control);
    const box = h("details", { class: "wb-acc wb-filters" },
      h("summary", {}, h("span", { class: "wb-acc-chev" }, icon("chevron-right", 14)), "Filters"),
      h("div", { class: "wb-filter-body" }, group("Area", area), group("Band", band), group("Search by name", name)));
    box.open = !phone.matches;
    area.addEventListener("change", () => { ui.area = area.value; renderResults(); });
    band.addEventListener("change", () => { ui.band = band.value; renderResults(); });
    name.addEventListener("input", () => { ui.name = name.value; renderResults(); });
    return { box, area, band, name };
  }

  function fillAreas() {
    const areas = model.areasOf(skills);
    if (ui.area && !areas.includes(ui.area)) ui.area = "";
    filters.area.replaceChildren(h("option", { value: "", text: "All areas" }), ...areas.map((a) => h("option", { value: a, text: a })));
    filters.area.value = ui.area;
  }

  /** An accordion for a skill: `details` keeps the open state, the keyboard and the screen reader's "expanded"; the set of open names is the page's. */
  function accordion(skill, className, summary, lines) {
    const details = h("details", { class: `wb-acc ${className}` }, summary, h("div", { class: "wb-acc-body wb-skill-detail" }, lines.map((line) => h("p", { text: line }))));
    details.open = ui.open.has(skill.name);
    details.addEventListener("toggle", () => {
      const on = details.open;
      if (on) ui.open.add(skill.name); else ui.open.delete(skill.name);
      for (const other of peers.get(skill.name) || []) if (other.open !== on) other.open = on;
    });
    peers.set(skill.name, [...(peers.get(skill.name) || []), details]);
    return details;
  }

  function listRow(skill) {
    const summary = h("summary", { class: "wb-skill-sum", "aria-label": rowName(skill) },
      h("span", { class: "wb-acc-chev" }, icon("chevron-right", 14)),
      h("code", { class: "wb-code wb-skill-name", title: String(skill.name), text: String(skill.name) }),
      h("span", { class: "wb-muted wb-skill-ver", text: String(skill.version) }),
      h("span", { class: "wb-muted wb-skill-area", text: String(skill.area) }),
      h("span", { class: "wb-skill-tier" }, bandNode(skill, "strong")),
      h("span", { class: "wb-skill-tier" }, bandNode(skill, "floor")));
    return accordion(skill, "wb-skill-row", summary, model.openLines(skill));
  }

  function card(skill) {
    const summary = h("summary", { "aria-label": rowName(skill) },
      h("span", { class: "wb-sc-1" }, code(skill.name), h("span", { class: "wb-muted", text: `${skill.version} · ${skill.area}` })),
      h("span", { class: "wb-muted wb-sc-2", text: `Manifest ${model.manifestText(skill)} · ${skill.runs_here ?? "-"} runs here` }),
      h("span", { class: "wb-sc-3" },
        model.TIER_COLUMNS.map(([tier]) => h("span", {},
          h("span", { class: "wb-muted", text: tier === "strong" ? "Reference" : "Floor" }),
          bandNode(skill, tier)))));
    return accordion(skill, "wb-skill-card", summary, model.detailLines(skill));
  }

  function renderResults() {
    const shown = model.filterSkills(skills, ui);
    peers = new Map();
    if (!shown.length) {
      results.replaceChildren(emptyBlock("No skill matches these filters."));
      return;
    }
    const head = h("div", { class: "wb-skill-head", "aria-hidden": "true" },
      ["", "Skill", "Version", "Area", "Reference model", "Floor model"].map((t) => h("span", { text: t })));
    results.replaceChildren(
      h("div", { class: "wb-skill-list", role: "group", "aria-label": CAPTION }, head, shown.map(listRow)),
      h("div", { class: "wb-skill-cards" }, shown.map(card)));
  }

  function legend() {
    return h("div", { class: "wb-legend" },
      model.BANDS.map((b) => chip(model.bandClass(b), b)),
      h("span", { class: "wb-muted wb-legend-note", text: "band per model tier, with the score" }));
  }

  function notice(spec) {
    return noticeCard(spec.title, [spec.sentence, ...spec.lines]);
  }

  function render(state) {
    if (state.status === "loading") {
      el.replaceChildren(loadingCard(model.LOADING));
      return;
    }
    if (state.status === "failed") {
      el.replaceChildren(failedCard(FAILED_TITLE, state.error));
      return;
    }
    skills = Array.isArray(state.data.skills) ? state.data.skills : [];
    const spec = model.checksNotice(state.data.checks);
    if (!skills.length) {
      el.replaceChildren(...[spec ? notice(spec) : null, emptyBlock("No skills are in scope of this project.")].filter(Boolean));
      return;
    }
    if (!filters) {
      filters = buildFilters();
      results = h("div", { class: "wb-results" });
    }
    fillAreas();
    renderResults();
    // the notice comes first: whether any skill runs as proven is decided by it (OPEN-26, recommended answer)
    reconcile(el, [spec ? notice(spec) : null, legend(), filters.box, results].filter(Boolean));   // the filters stay attached: the search field keeps its focus
  }

  return {
    el,
    set: render,
    dispose() {
      phone.removeEventListener("change", onPhone);
    },
  };
}
