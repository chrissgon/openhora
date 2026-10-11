// The screens that come with later packages (the Building, the Floor, the Lobby and the control room): inside the shared
// frame, a panel with the project's status counts, as the plumbing package left it. It exercises the route, the frame and
// the client end to end; the real screens replace it.

import { h } from "../dom.js";
import { createPanel } from "../frame/panel.js";

const TITLES = { building: "Building", floor: "Floor", lobby: "Lobby", control: "Control room" };

/** Requests by state, as [[state, count], ...] in the order the states first appear. */
export function countByState(requests) {
  const counts = new Map();
  for (const item of Array.isArray(requests) ? requests : []) {
    const state = typeof item.state === "string" ? item.state : "unknown";
    counts.set(state, (counts.get(state) || 0) + 1);
  }
  return [...counts.entries()];
}

/** Create the panel for a route in the frame. Returns {el, update(snapshot, projectId, subtitle)}. */
export function createPlaceholder(frame, route) {
  const panel = createPanel({ title: TITLES[route.screen] || "Screen", subtitle: "", icon: route.screen === "control" ? "server" : "building-2", width: route.screen === "control" ? "wide" : "narrow" });
  frame.main.append(panel.el);
  return {
    el: panel.el,
    update(snapshot, projectId, subtitle) {
      const project = (snapshot.projects || []).find((p) => p.id === projectId);
      const detail = project ? snapshot.details[projectId] : null;
      const parts = [];
      parts.push(h("p", { class: "wb-muted", text: "This screen comes with a later package. These are the project's counts for now." }));
      if (!project) {
        parts.push(h("p", { class: "notice pui-soft pui-error", role: "alert", text: snapshot.loaded ? "The service has no such project." : "Loading..." }));
      } else if (project.config && !project.config.accepted) {
        parts.push(h("p", { class: "notice pui-soft pui-error", text: project.message || "The project's configuration is not accepted yet." }));
      } else if (detail && detail.error && !detail.status) {
        parts.push(h("p", { class: "notice pui-soft pui-error", role: "alert", text: detail.error.message }));
      } else if (detail && detail.status) {
        const pending = (detail.status.pending || []).length;
        const states = countByState(detail.status.requests);
        parts.push(
          h("p", {}, h("span", { class: "wb-muted", text: "Open decisions: " }), String(pending)),
          states.length
            ? h("div", { class: "table-wrap" }, h("table", { class: "pui-table" },
              h("thead", {}, h("tr", {}, h("th", { text: "Requests" }), h("th", { text: "Count" }))),
              h("tbody", {}, states.map(([name, count]) => h("tr", {}, h("td", { text: name }), h("td", { text: String(count) }))))))
            : h("p", { class: "wb-muted", text: "No requests yet." }));
      }
      panel.body.replaceChildren(...parts);
      const name = project ? project.name : "";
      panel.el.querySelector(".wb-panel-title").textContent = route.screen === "building" && name ? name : (TITLES[route.screen] || "Screen");
      panel.el.querySelector(".wb-panel-sub").textContent = subtitle || name;
    },
  };
}
