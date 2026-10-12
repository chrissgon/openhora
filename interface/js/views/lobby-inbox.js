// The Lobby's Inbox tab (handoff lobby.md, "Inbox tab"): the Floor's Inbox (floor/inbox.js and its cards) fed with the planning agent's
// open decisions, those with no agent (a decision on a request) and those of the planning agent. A plan on a request that a message
// of the planning agent names has its card under that message in the Conversation; here it is a line that points there, so a plan
// card is drawn in one place only (OPEN-24). Every other decision has its card here. This module draws and hands the cards their
// environment; every write is sent by the Floor's cards through floor/actions.js.

import { fill, h } from "../dom.js";
import { PLANNING } from "../floor-model.js";
import { actions } from "../floor/actions.js";
import { createInbox } from "../floor/inbox.js";
import * as format from "../format.js";
import * as router from "../router.js";
import { pointerLine } from "./lobby-request.js";

export const ONLY_POINTERS_TEXT = "Nothing else waits for you here.";

/**
 * Create the Lobby's Inbox. env: {project, now(), refresh() (read the screen's data again)}. Returns {el, update({cards, pointers,
 * requests, resolved, selected, loading}), busy(), reset()}; cards and pointers come from lobby-model.js `inboxParts`.
 */
export function createLobbyInbox(env) {
  const { project } = env;
  const inbox = createInbox({
    project, now: env.now, api: actions, refresh: env.refresh,
    links: {
      // the planning agent's own tasks and every decision on a request belong to the Lobby; another agent has a floor
      floor: (agent) => (agent === PLANNING ? router.lobbyHash(project) : router.floorHash(project, agent)),
      lobby: () => router.lobbyHash(project),
      parent: () => router.buildingHash(project),
      open: (item, path) => router.lobbyDeskHash(project, path),
    },
  });
  const pointerBox = h("div", { class: "wb-lobby-pointers" });
  const el = h("div", { class: "wb-lobby-inbox" }, pointerBox, inbox.el);
  let shown = "";

  return {
    el,
    update({ cards, pointers, requests, resolved, selected, loading }) {
      const now = env.now();
      const key = JSON.stringify(pointers.map((p) => [p.id, p.title, p.task_id]));
      if (key !== shown) {
        shown = key;
        fill(pointerBox, pointers.map((item) => pointerLine(item, now, h("a", {
          class: "pui-link pui-theme", href: router.lobbyHash(project), text: "Open in the Conversation",
          "aria-label": `Open ${format.kindWord(item.kind)} ${item.id} in the Conversation`,
        }))));
      }
      inbox.update({ decisions: cards, requests, resolved, selected, loading, emptyText: pointers.length ? ONLY_POINTERS_TEXT : "" });
    },
    busy() {
      return inbox.busy();
    },
    /** A document was closed: the focus goes back to the "Open" link of the card that opened it. */
    focusOpen(path) {
      inbox.focusOpen(path);
    },
    reset() {
      inbox.reset();
    },
  };
}
