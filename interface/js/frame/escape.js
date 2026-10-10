// The Escape key, in one place (WP-9.11). The page had a handler in each screen and they disagreed: in the Control room and in the Lobby
// Escape did nothing after the person had used an object. One handler, one order, stopping at the first step that applies:
//   1. a field has the focus: nothing (a draft is not thrown away);
//   2. a dialog is open: it closes;
//   3. a document or a selected decision is open in the Floor or the Lobby: it closes (a document back to the tab it was opened from, a
//      decision to the Inbox list);
//   3b. the Lobby's "New request" form is open (R-44): it goes back to the conversation, the draft stays;
//   4. a menu or a list is open (the project switcher, the open "Waiting for you" card, the command panel of the switcher's foot, the request list): it closes;
//   5. a scene object is selected or hovered by the keyboard: the selection is cleared;
//   6. else go up one level, always (M-1): the Floor and the Lobby to the Building, the Building to the City (`#/city`, with one project too),
//      the Control room to the screen it was opened from (else the Building of the project); on the City, nothing.
// Pure: no document and no window, so a test can run every step.

import * as router from "../router.js";
import { closeHash } from "./origin.js";

/**
 * state: {route (router.parse), field, dialog, menu, selection, form: booleans, from: the hash the Control room was opened from, or null,
 * origin: "inbox" when the open document came from the Inbox (frame/origin.js), else null}.
 * Returns {step, hash?}: step is "none", "dialog", "document", "form", "menu", "selection" or "up"; `hash` is where the page goes for "document" and "up".
 */
export function escapeStep({ route, field = false, dialog = false, menu = false, selection = false, form = false, from = null, origin = null }) {
  if (field) return { step: "none" };
  if (dialog) return { step: "dialog" };
  const room = route.screen === "floor" || route.screen === "lobby";
  if (room && route.path) return { step: "document", hash: closeHash(route, origin) };   // the same hash as the viewer's "Close"
  if (room && route.pending !== null && route.pending !== undefined) return { step: "document", hash: route.screen === "lobby" ? router.lobbyHash(route.project, "inbox") : router.floorHash(route.project, route.agent, "inbox") };
  if (room && form) return { step: "form" };
  if (menu) return { step: "menu" };
  if (selection) return { step: "selection" };
  if (route.screen === "floor" || route.screen === "lobby") return { step: "up", hash: router.buildingHash(route.project) };
  if (route.screen === "building") return { step: "up", hash: router.cityHash() };
  if (route.screen === "control") return { step: "up", hash: from || router.buildingHash(route.project) };
  return { step: "none" };
}

/** True when the element is a place the person types in. */
export function isField(element) {
  if (!element) return false;
  const tag = element.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || Boolean(element.isContentEditable);
}
