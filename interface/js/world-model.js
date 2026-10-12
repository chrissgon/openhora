// What the world (scene/world.js) is shown from the service's data, in a plain shape with no three.js and no document: every lot (at most
// four) with the floors of its building, the City's card words and, for the building the route names, its work-order tag. The City and the
// Building both pass it: the City with no focus, the Building with the project of the route as the focus.

import * as fm from "./floor-model.js";
import * as model from "./model.js";
import { owlTargets } from "./owl-words.js";
import { asking } from "./scene/room-words.js";
import { seatsOf } from "./seats.js";

/**
 * snapshot: the page's snapshot; `now` a Date; opts: {selectedId (the project whose card is marked), marked (the id of the building that keeps a
 * selection outline: the project the switcher has chosen), focus (the project whose building is open, or null), floor (the floor of it the route is
 * on, or null), frame (the one floor a phone shows, or null), room (the words of the floor's room: {tips, board, door}), documents (the rows of
 * `artifacts`, for every project that is the focus), ready (false while the first read is loading)}.
 */
export function worldModel(snapshot, now, { selectedId = null, marked = null, focus = null, floor = null, frame = null, room = null, documents = null, ready = true } = {}) {
  const city = model.city(snapshot, now);
  const lots = city.buildings.slice(0, model.MAX_LOTS).map((b) => {
    const view = fm.building(snapshot, b.id);
    const scene = view ? fm.buildingScene(view, b.id === focus ? documents : null, { ready }) : null;
    return {
      id: b.id, name: b.name, accepted: b.accepted, decisions: b.decisions, runningTask: b.runningTask,
      tip: model.tooltipOf(b), sub: model.subOf(b),
      floors: scene ? scene.floors : [], selected: scene ? scene.selected : null, tag: view ? view.tag : null,
    };
  }).filter((lot) => lot.floors.length > 0);
  const there = focus && lots.some((l) => l.id === focus) ? focus : null;
  let roomOut = there && floor ? room : null;
  // The words of a room may carry its own state (the Lobby is working while a turn runs), its decisions, its documents' count (and the sheets and drawers older code reads): they replace the
  // snapshot's for that one floor.
  if (there && floor && room) {
    const lot = lots.find((l) => l.id === there);
    const at = lot.floors.findIndex((f) => f.name === floor);
    if (at >= 0) {
      const f = lot.floors[at];
      const state = room.state || f.state;
      lot.floors[at] = {
        // the seats follow the room's own state (the Lobby works while a turn runs): the holders are the floor's, the owl of a floor with none is by the state
        ...f, state, seats: state !== f.state ? seatsOf(f.holders, { state, accepted: lot.accepted, maxParallel: f.maxParallel }) : f.seats, window: room.window || f.window, decisions: room.decisions !== undefined ? room.decisions : f.decisions,
        sheets: room.sheets || f.sheets, drawers: room.drawers !== undefined ? room.drawers : f.drawers,
        documents: room.documents !== undefined ? room.documents : f.documents,
      };
      // each owl of the room is selected on its own (PAR-7e): its words and its destination, from the seats just settled, the agent's tasks and its open decisions
      const detail = snapshot.details[there];
      const status = detail && detail.status ? detail.status : null;
      const shown = lot.floors[at];
      roomOut = {
        ...room,
        owls: owlTargets({
          seats: shown.seats, tasks: status ? fm.agentTasks(status, floor) : [], decisions: status ? fm.agentDecisions(status, floor) : [],
          floorTip: room.tips && room.tips.agent, asks: asking(shown),
        }),
      };
    }
  }
  return {
    ready, selectedId, marked: marked && lots.some((l) => l.id === marked) && !there ? marked : null, outlined: there && floor ? `floor:${floor}` : null,
    focus: there, floor: there ? floor : null, frame: there ? frame : null, room: roomOut, lots, label: city.canvasLabel,
  };
}
