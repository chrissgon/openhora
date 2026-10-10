// The Connections tab of the Control room: the requirement classes the skills in scope need, the secrets by name (never a
// value, never a masked value or a length), the eval image and the platform. It shows what the `connections` operation
// returned. The Platform card shows `here` and `evidence` and the chip `same` gives; it states no consequence of a
// difference (the supervisor's decision: the runtime has none, so the page states none).

import { h } from "../dom.js";
import { commandBlock } from "../frame/command.js";
import * as model from "./control-model.js";
import { cell, chip, code, failedCard, FAILED_TITLE, loadingCard, sectionHead, tableCard } from "./control-parts.js";

/**
 * "Needed by" (E-15, R-54): up to four skills the list as it is; past four, `<n> skills` as a disclosure in the theme colour with the list under the count. The full list
 * stays in the control's accessible name, so a screen reader hears it without opening anything.
 */
function neededCell(r) {
  if (!r.count) return "-";
  if (r.count <= model.NEEDED_LIST) return code(r.needed);
  return h("details", { class: "wb-need" },
    h("summary", { "aria-label": `${r.count} skills: ${r.needed}`, text: `${r.count} skills` }),
    code(r.needed));
}

function classesTable(rows) {
  const head = ["Class", "Provider", "Status", "Needed by"];
  return h("table", { class: "pui-table wb-ctable wb-stackable" },
    h("caption", { class: "wb-sr", text: "Requirement classes the skills in scope need, and whether a provider was found" }),
    h("thead", {}, h("tr", {}, head.map((t) => h("th", { scope: "col", text: t })))),
    h("tbody", {}, rows.map((r) => h("tr", {},
      cell("Class", code(r.class)),
      h("td", { "data-label": "Provider", title: r.note || null }, r.provided ? r.provider : h("span", { class: "wb-muted", text: r.provider })),
      cell("Status", chip(`pui-chip ${r.found ? "pui-success" : "pui-error"} pui-soft`, r.status)),
      cell("Needed by", neededCell(r))))));
}

function secretsTable(rows) {
  const head = ["Name", "Status", "Where"];
  return h("table", { class: "pui-table wb-ctable wb-stackable" },
    h("caption", { class: "wb-sr", text: "Secrets by name: found or missing, and where; never a value" }),
    h("thead", {}, h("tr", {}, head.map((t) => h("th", { scope: "col", text: t })))),
    h("tbody", {}, rows.map((r) => h("tr", { "aria-label": model.secretName(r) },
      cell("Name", code(r.name)),
      cell("Status", chip(`pui-chip ${r.found ? "pui-success" : "pui-error"} pui-soft`, r.status)),
      cell("Where", r.where)))));
}

function imageCard(spec) {
  return h("div", { class: "pui-card wb-ccard" },
    sectionHead("Image"),
    h("div", { class: "wb-ccard-line" }, h("strong", { class: "mono", text: spec.name }), chip(`pui-chip ${spec.tone} pui-soft`, spec.chip)),
    h("p", { class: "wb-muted", text: spec.sentence }));
}

// The Platform card: "This machine" and "Evidence" on two lines; when the platforms differ the card spans the width and says both on one line (E-11: no consequence is stated).
function platformCard(spec) {
  const badge = spec.chip ? chip(`pui-chip ${spec.tone} pui-soft`, spec.chip) : null;
  const here = h("span", {}, "This machine: ", code(spec.here));
  return h("div", { class: `pui-card wb-ccard${spec.differs ? " is-wide" : ""}` },
    sectionHead("Platform"),
    spec.differs
      ? h("div", { class: "wb-ccard-line" }, h("span", {}, "This machine: ", code(spec.here), " · Evidence: ", code(spec.evidence)), badge)
      : [h("div", { class: "wb-ccard-line" }, here, badge), h("p", {}, "Evidence: ", code(spec.evidence))]);
}

// What the local service found at its start (`service` of the answer): one row for each verdict that is not ok; where the terminal has a
// command that fixes it, the component shows the service's own text of it.
function serviceCard(rows) {
  return h("div", { class: "pui-card wb-ccard wb-service wb-service-card" },
    rows.map((r) => h("div", { class: "wb-svc wb-service-row" },
      h("strong", { text: r.what }),
      r.command ? commandBlock({ command: r.command, sentence: r.sentence }) : h("p", { class: "wb-muted", text: r.sentence }))));
}

/** The tab. Returns {el, set(state)}; state: {status: "loading"|"ready"|"failed", data, error}. */
export function createConnectionsTab() {
  const el = h("div", { class: "wb-tab-body" });
  return {
    el,
    set(state) {
      if (state.status === "loading") {
        el.replaceChildren(loadingCard(model.LOADING));
        return;
      }
      if (state.status === "failed") {
        el.replaceChildren(failedCard(FAILED_TITLE, state.error));
        return;
      }
      const data = state.data;
      const classes = model.classRows(data);
      const secrets = model.secretRows(data);
      const platform = model.platformCard(data);
      const note = typeof data.secrets_note === "string" && data.secrets_note ? data.secrets_note : null;
      const service = model.serviceRows(data.service);
      el.replaceChildren(...[
        sectionHead("Requirement classes"),
        tableCard(classesTable(classes)),
        sectionHead("Secrets (names only, never a value)"),
        tableCard(secretsTable(secrets)),
        note ? h("p", { class: "wb-muted wb-note", text: note }) : null,
        service.length ? sectionHead("Service") : null,
        service.length ? serviceCard(service) : null,
        h("div", { class: "wb-ccards" }, imageCard(model.imageCard(data)), platformCard(platform)),
      ].filter(Boolean));
    },
  };
}
