// The room of a floor in the round's style (R-21, R-23, R-23b, R-28, R-31, R-41, R-42, R-49): the same room in the City's building, in the Building's cutaway, on the Floor
// and in the Lobby, because it is the same meshes. A room is the floor's slab, its floor (a tone that says what the agent does: a lit room is a soft warm tone), two back
// walls (the left one pierced by two windows, or by one window and the Lobby's door) and, in them, the agent's three ways in: the owl, the task board with a note for each
// task, and the one bookcase with a binder for each document (sixteen at most, M-7). The agent's desk and chair stand along the room's right edge. No tray, no table of sheets, no lamp, no roof; two plants stand by the windows (plants.js).
// Everything static is baked into a few meshes in the tones of `roomTones` (kit.batch); the tower (tower.js) puts a room in each of its floors and closes the building round
// them with the walls the City shows. No colour and no name is written here: the page's measures are in room-frame.js and furniture.js.

import { BOARD_RIGHT, CASE_LEFT, DOOR, NOTE_CAPACITY, SEAT, bindersShown, bookcase, chair, desk, door, taskBoard } from "./furniture.js";
import { boxBrackets, planeBrackets } from "./marks.js";
import { buildOwl, towardCamera } from "./owl-build.js";
import { roomTones } from "./palette.js";
import { plants } from "./plants.js";
import { owlScale, pageBatch, pageFrame } from "./room-frame.js";

export const W = 6.4;
export const D = 4.8;
export const SLAB = 0.2;
export const H = 2.8;
export const P = SLAB + H;   // one floor, closed: the slab and its walls
export const GAP = 0.45;     // the floors open by this much: the page leaves 0.9 of its units between a floor's walls and the slab above (3.78 a floor, 2.88 of it room)
export const BASE = 0.2;

/** The page's room on this building's constants. */
export const FRAME = pageFrame({ W, D, H, SLAB });

/** The y of floor i for a pitch (P + GAP when open). */
export function floorY(i, pitch = P + GAP) {
  return BASE + i * pitch;
}

// The two windows of the left wall, as the page draws them (page units): the opening's z range and y range, and the Lobby's door where the nearer one is.
const WINDOWS = [{ z0: 0.916, z1: 2.804 }, { z0: 3.087, z1: 4.976 }];
const GLASS = { y0: 0.818, y1: 2.188, back: 0.06, rail: [1.618, 1.718], sill: [0.72, 0.82] };
const WALL = 0.2;
const BOARD_LEFT = 0.535;

/** Where the HTML labels of a room stand, relative to the floor's origin, in world units: over the board of notes, over the door. */
export function anchors() {
  return {
    board: { x: FRAME.X((BOARD_LEFT + BOARD_RIGHT) / 2), y: FRAME.Y(2.37), z: FRAME.Z(WALL) },
    door: { x: FRAME.X(WALL), y: FRAME.Y(DOOR.top), z: FRAME.Z((DOOR.z0 + DOOR.z1) / 2) },
  };
}

/** The tone of a room's floor: lit while the agent is active in an accepted project, dark when it is off or the project is not accepted, the plain tone otherwise (R-21). */
export function floorTone(tones, { accepted, state, window }) {
  if (accepted && window === "lit") return tones.floorLit;
  if (!accepted || state === "off") return tones.floorOff;
  return tones.floor;
}

/** The pose of the owl for a floor: none when its agent is off or its project is not accepted (R-41), else by state. */
export function owlPose({ accepted, state }) {
  if (!accepted || state === "off") return null;
  return state === "working" ? "working" : state === "waiting" ? "waiting" : "idle";
}

/** The glass of a window state: warm white while lit, the project's glass otherwise, the wall's own tone for a project that is not accepted. */
function glassOf(tones, accepted, window) {
  if (!accepted) return tones.glassOff;
  return window === "lit" ? tones.glassLit : tones.glass;
}

// --- the shell: slab, floor, walls, windows -----------------------------------------------------------------------------------------------

function shell(pb, tones, tone, lobby) {
  const top = FRAME.wallTop;
  pb.box(tones.ledge, -0.17, -FRAME.slab, -0.17, 7.34, FRAME.slab, 5.94);
  pb.flat(tone, 0, 0, 7, 5.6, 0.004);
  pb.box(tones.wall, 0, 0, 0, 7, top, WALL);
  // the left wall, piece by piece round its openings: the pier before an opening shows its jamb, the piece under it its bottom, the piece over it nothing
  const openings = WINDOWS.map((w, k) => (lobby && k === 1 ? { z0: DOOR.z0, z1: DOOR.z1, y0: 0, y1: DOOR.top, jamb: tones.doorShade, door: true } : { ...w, y0: GLASS.y0, y1: GLASS.y1, jamb: tones.jamb, door: false }));
  const t = tones.wall;
  let cursor = 0;
  for (const o of openings) {
    if (o.z0 > cursor) pb.box({ top: t.top, left: o.jamb, right: t.right }, 0, 0, cursor, WALL, top, o.z0 - cursor);
    if (o.y0 > 0) pb.box({ top: tones.under, left: t.left, right: t.right }, 0, 0, o.z0, WALL, o.y0, o.z1 - o.z0);
    if (o.y1 < top) pb.box(t, 0, o.y1, o.z0, WALL, top - o.y1, o.z1 - o.z0);
    cursor = o.z1;
  }
  pb.box(t, 0, 0, cursor, WALL, top, 5.6 - cursor);
  return openings;
}

/** The windows' trims, uprights, rails and boards under them (still), and their glass (a batch of its own: a window's state is one repaint). */
function windows(pb, glassPb, tones, glass, openings) {
  const E = 0.002;
  for (const o of openings) {
    if (o.door) continue;
    glassPb.side(glass, o.z0, o.y0, o.z1, o.y1, GLASS.back);
    const mid = (o.z0 + o.z1) / 2;
    pb.side(tones.mull, mid - 0.05, o.y0, mid + 0.05, o.y1, GLASS.back + E);
    pb.side(tones.mull, o.z0, GLASS.rail[0], o.z1, GLASS.rail[1], GLASS.back + E);
    const w = 0.04;
    for (const [a0, b0, a1, b1] of [[o.z0 - w, o.y0 - w, o.z1 + w, o.y0], [o.z0 - w, o.y1, o.z1 + w, o.y1 + w], [o.z0 - w, o.y0, o.z0, o.y1], [o.z1, o.y0, o.z1 + w, o.y1]]) {
      pb.side(tones.trim, a0, b0, a1, b1, WALL + E);
    }
    pb.box(tones.board, WALL, GLASS.sill[0], o.z0 - 0.1, 0.18, GLASS.sill[1] - GLASS.sill[0], o.z1 - o.z0 + 0.2);
  }
}

// --- the room --------------------------------------------------------------------------------------------------------------------------------

/**
 * Draw the room of floor `f` into `parent` (a group at the floor's origin). f: {name, state, window, decisions, lobby, notes: ["done" | "run" | "left"], documents}.
 * ctx: {lot, accepted, motions}. Returns the parts a screen points at: {agent (the owl's group, or null), board, shelf, door (or null), marks: {room, agent, board, shelf, door}}
 * and the setters that change the room in place: setWindow(state), setNotes(list), setDocuments(n); `dispose()` frees the geometry and the materials the room made.
 */
export function fillFloor(kit, parent, f, ctx) {
  const { THREE, palette } = kit;
  const tones = roomTones(palette);
  const room = new THREE.Group();
  parent.add(room);
  const make = (batch) => pageBatch(batch, FRAME);
  const holder = () => {   // what a hit shows for the pointer: it stays while the brackets in it are made again
    const group = new THREE.Group();
    group.visible = false;
    group.userData.brackets = true;   // brackets are drawn, never picked: a hit's own meshes are what the pointer meets (`pick.js`)
    return group;
  };
  const accepted = ctx.accepted !== false;
  const tone = floorTone(tones, { accepted, state: f.state, window: f.window });

  // the still shell and furniture, one mesh; the glass its own
  const still = kit.batch();
  const glassBatch = kit.batch();
  const pb = make(still);
  const openings = shell(pb, tones, tone, Boolean(f.lobby));
  windows(pb, make(glassBatch), tones, glassOf(tones, accepted, f.window), openings);
  desk(pb, tones);
  chair(pb, tones);
  plants(THREE, pb, FRAME, tones);
  still.mesh(room, { cast: false });
  const glass = glassBatch.mesh(room, { cast: false });

  // the door of the Lobby: an object of its own (it goes to the Control room)
  let doorGroup = null;
  let doorMarks = null;
  if (f.lobby) {
    doorGroup = new THREE.Group();
    room.add(doorGroup);
    const batch = kit.batch();
    door(make(batch), tones);
    batch.mesh(doorGroup, { cast: false });
    doorMarks = holder();
    room.add(doorMarks);
    doorMarks.add(planeBrackets(kit, make, { plane: "x", at: WALL + 0.02, a0: DOOR.z0 - 0.07, a1: DOOR.z1 + 0.07, y0: -0.03, y1: DOOR.top + 0.07, arm: 0.45, tone: tones.bracket }));
  }

  // the board of notes and the bookcases: each a group that stays while what is in it is made again, and the brackets that mark it
  const board = new THREE.Group();
  const shelf = new THREE.Group();
  const boardMarks = holder();
  const shelfMarks = holder();
  room.add(board, shelf, boardMarks, shelfMarks);
  const state = { notes: [], documents: 0, shown: 0 };
  // what a holder shows is one mesh that stays while it is made again: its geometry is swapped in place and the old one freed, so that nothing of the room is replaced
  const refill = (holder, mesh) => {
    const old = holder.children[0];
    if (!old) {
      holder.add(mesh);
      return;
    }
    kit.release(old.geometry);
    old.geometry = mesh.geometry;
  };
  const buildBoard = () => {
    const batch = kit.batch();
    state.shown = taskBoard(make(batch), tones, state.notes);
    refill(board, batch.mesh(new THREE.Group(), { cast: false }));
    refill(boardMarks, planeBrackets(kit, make, { plane: "z", at: WALL + 0.02, a0: BOARD_LEFT - 0.07, a1: BOARD_RIGHT + 0.07, y0: 0.565, y1: 2.4, arm: 0.63, tone: tones.bracket }));
  };
  const buildShelf = () => {
    const batch = kit.batch();
    const pbs = make(batch);
    bookcase(pbs, tones, CASE_LEFT, 0, bindersShown(state.documents));
    refill(shelf, batch.mesh(new THREE.Group(), { cast: false }));
    refill(shelfMarks, boxBrackets(kit, make, { x0: CASE_LEFT - 0.12, x1: CASE_LEFT + 1.45 + 0.12, z0: 0.1, z1: 0.92, y0: 0, y1: 2.4, arm: 0.45, drop: 0.475, tone: tones.bracket }));
  };
  const setCounts = (documents, notes) => {
    state.documents = typeof documents === "number" ? documents : 0;
    state.notes = notes;
  };
  setCounts(f.documents, f.notes || []);
  buildShelf();
  buildBoard();

  // the owl, standing where the page puts it for its state
  const pose = owlPose({ accepted, state: f.state });
  let agent = null;
  let agentMarks = null;
  let owl = null;
  if (pose) {
    owl = buildOwl(kit, pose, { scale: owlScale(FRAME), mix: palette.mix, floorTone: tone, handLift: pose === "working" ? 0.5 : 0 });
    agent = owl.group;
    const [px, pz] = SEAT.owl[pose];
    const lift = towardCamera(THREE).multiplyScalar(pose === "working" ? 0.7 : 0.3);
    agent.position.set(FRAME.X(px), FRAME.Y(0.01), FRAME.Z(pz)).add(lift);
    room.add(agent);
    ctx.motions.push(owl.motion);
    // one size round the owl for every pose, and a corner behind it is hidden by it
    agentMarks = holder();
    room.add(agentMarks);
    agentMarks.add(boxBrackets(kit, make, { x0: px - 0.84, x1: px + 0.84, z0: pz - 0.84, z1: pz + 0.84, y0: 0, y1: 1.82, arm: 0.45, drop: 0.475, tone: tones.bracket }));
  }

  // the room's own brackets (R-28): round its base and at the top of its walls
  const roomMarks = holder();
  room.add(roomMarks);
  roomMarks.add(boxBrackets(kit, make, { x0: -0.42, x1: 7.42, z0: -0.42, z1: 6.02, y0: 0, y1: FRAME.wallTop, arm: 1.12, drop: 0.84, tone: tones.bracket }));

  const paint = (mesh, colour) => {
    const attribute = mesh.geometry.getAttribute("color");
    for (let k = 0; k < attribute.count; k++) attribute.setXYZ(k, colour.r, colour.g, colour.b);
    attribute.needsUpdate = true;
  };
  return {
    agent, board, shelf, door: doorGroup, pose, motion: owl ? owl.motion : null,
    marks: { room: roomMarks, agent: agentMarks, board: boardMarks, shelf: shelfMarks, door: doorMarks },
    get notesShown() { return state.shown; },
    /** How many binders the bookcase shows (M-7: one bookcase, sixteen at most). */
    get binders() { return bindersShown(state.documents); },
    setWindow(window) {
      if (glass) paint(glass, glassOf(tones, accepted, window));
    },
    /** The notes of the board become `list` (a task's state each: "done", "run", "left"). */
    setNotes(list) {
      state.notes = list;
      buildBoard();
    },
    /** The bookcase holds `n` documents (sixteen binders at most: M-7). */
    setDocuments(n) {
      setCounts(n, state.notes);
      buildShelf();
    },
    capacity: () => NOTE_CAPACITY,
    /** Free the geometry and the materials the room made, and take it out of its floor. */
    dispose() {
      if (owl) owl.dispose();
      room.traverse((node) => { if (node.geometry) kit.release(node.geometry); });
      parent.remove(room);
    },
  };
}
