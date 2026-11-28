// What the office shows, from the snapshot the page already reads: pure, no document, no client. The number is the open decisions of the
// project (the "Waiting for you" rows), never a count of agents; each agent carries its state, its decisions and where a click on it goes.

import * as fm from "../floor-model.js";
import * as format from "../format.js";
import * as model from "../model.js";
import * as router from "../router.js";

/** 32-bit FNV-1a over the UTF-16 code units of a text: a stable number for a name (the figure's hue). */
export function fnv1a32(text) {
  let hash = 2166136261;
  const value = String(text);
  for (let i = 0; i < value.length; i++) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

/**
 * The office of one project: {ready, accepted, count, agents}, or {ready: false} when the project or its detail is not in the snapshot.
 * agents: [{name, display, state, decisions, link, look}] in floor order. `link` is the card of the agent's oldest open decision, else its floor.
 */
export function officeOf(snapshot, projectId, now) {
  const project = ((snapshot && snapshot.projects) || []).find((p) => p.id === projectId);
  const detail = project && snapshot.details ? snapshot.details[projectId] : null;
  if (!project || !detail) return { ready: false };
  const status = detail.status || null;
  const { accepted } = model.acceptance(project, detail);
  const rows = model.waitingRows(snapshot, now, projectId);
  const agents = fm.floorAgents(detail).list.map((agent) => {
    const name = agent.name || fm.PLANNING;
    const ids = new Set(fm.agentDecisions(status, name).map((item) => item.id));
    const mine = rows.filter((row) => ids.has(row.id));
    return {
      name,
      display: format.agentWord(name),
      state: fm.stateOf(agent, status, accepted),
      decisions: mine.length,
      link: mine.length ? mine[0].link : router.agentHash(projectId, name),
      look: { hue: fnv1a32(name) % 360 },
    };
  });
  return { ready: true, accepted, count: rows.length, agents };
}
