// Where an open document goes back to (A-19). The hash names the document and the room, never the tab it was opened from, so the
// screens that show a document (the Floor and the Lobby) tell this module every route they draw, and this module keeps one fact: the
// tab (and the selected decision, if any) of the route the document was opened from, in the same room. A document opened from a card's
// "Open" link, a Tasks or Agent tab's link, a Desk row or a sheet of the room goes back to exactly there; one opened by a hash typed in
// the bar (no route before it in this room) goes back to the Desk. "Close", a phone's dialog and Escape all read it, so they cannot
// disagree. Memory only.

import * as router from "../router.js";

let previous = null;   // the last route told: {screen, project, agent, tab, pending, path (a boolean)}
let origin = null;     // {tab, pending} of the route the open document came from, or null

/** Tell the module the route a screen is drawing. Called on every draw: the same route again changes nothing. */
export function track(route) {
  const here = { screen: route.screen, project: route.project, agent: route.agent || null, tab: route.tab || null,
    pending: route.pending === undefined ? null : route.pending, path: Boolean(route.path) };
  const sameRoom = previous !== null && previous.screen === here.screen && previous.project === here.project && previous.agent === here.agent;
  if (!here.path || !sameRoom) origin = null;
  else if (!previous.path) origin = { tab: previous.tab, pending: previous.pending };   // the document just opened: from the route before it
  // else a document was already open in this room (a poll, or one document replaced by another): the origin stays
  previous = here;
}

/** A screen that was told routes is taken down: what it knew is forgotten, so a later deep link is a direct entry. */
export function reset() {
  previous = null;
  origin = null;
}

/** {tab, pending} the open document was opened from (tab null is the room's first tab), or null when there is none (the Desk then). */
export function current() {
  return origin;
}

/** The hash that closes the document of `route`: the place it was opened from, else the Desk of the same room. */
export function closeHash(route, from) {
  const tab = from ? from.tab : "desk";
  const pending = from ? from.pending : null;
  return route.screen === "lobby" ? router.lobbyHash(route.project, tab, pending) : router.floorHash(route.project, route.agent, tab, pending);
}

/** Close the document of `route`: the same hash Escape goes to. */
export function close(route) {
  window.location.hash = closeHash(route, origin);
}
