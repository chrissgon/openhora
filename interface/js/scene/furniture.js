// The furniture of a room in the round's style (R-23, R-23b, R-42, R-49), every measure taken off `building.html`, `floor.html` and `lobby.html` in the page's
// units (room-frame.js) and every tone from `roomTones` (palette.js): the bookcase with its binders, the task board with its notes, the agent's desk and
// the office chair, the Lobby's door. Each function draws into a batch of page units (`pageBatch`); a layer that stands on another (a label on a binder,
// a note on the board) is put a hair in front of it, as the page paints it over. No tray, no table of sheets, no cabinet, no lamp (the two plants are plants.js's, A-45): the
// room's three objects are its three ways in (R-23b). Nothing here knows a project or an agent.

const E = 0.002;   // the distance between a layer and the one under it, in page units

// --- the bookcase --------------------------------------------------------------------------------------------------------------------

export const BINDERS_PER_CASE = 16;   // four shelves of four
const CASE = { w: 1.45, left: 5.38, front: 0.76, shelf: 0.485, board: 0.065, rows: 4, perRow: 4 };

/** The left edge of the room's one bookcase against the back wall, in page units: at the right-hand end (M-7: every room has one, whatever its documents; it is an object to open, not storage). */
export const CASE_LEFT = CASE.left;

/** The binders a room shows: one for each document up to what the one bookcase holds. */
export const bindersShown = (documents) => Math.min(Math.max(0, documents || 0), BINDERS_PER_CASE);

// a binder's width, height and how far its spine stands out of the case, cycling as the page draws its first seven
const WIDTHS = [0.21, 0.17, 0.24, 0.18, 0.17, 0.24, 0.18];
const HEIGHTS = [0.38, 0.31, 0.41, 0.34];
const PROUD = [0.029, 0.017, 0.029, 0.017, 0.064, 0.046, 0.064];
const COVERS = [1, 3, 1, 3, 2, 4, 2];

/** The cover tone (1 to 4) of document number `n`, counted from 0, as the page's first seven are (1, 3, 1, 3, 2, 4, 2, then again). */
export const coverOf = (n) => COVERS[n % COVERS.length];

/** One binder (document number `n`, counted from 0) standing on a shelf at x: a cover with volume, its spine with ribs, a label of three lines and a finger hole. Returns its width. */
function binder(pb, t, n, x, shelfTop) {
  const w = WIDTHS[n % WIDTHS.length];
  const h = HEIGHTS[(n % BINDERS_PER_CASE) % 4];
  const kit = t.binder(coverOf(n));
  const zf = CASE.front + 0.004 + PROUD[n % PROUD.length];
  const z = zf + E;
  pb.box({ top: kit.outline, left: kit.outline, right: kit.outline }, x - 0.012, shelfTop, 0.7, w + 0.024, h + 0.012, zf + 0.006 - 0.7);   // its own cover a step darker, never a dark line
  pb.box(kit.face, x, shelfTop, 0.7, w, h, zf - 0.7 + 0.008);
  pb.flat(kit.pages, x + 0.02, CASE.front + 0.01, x + w - 0.01, zf - 0.004, shelfTop + h + 0.014);
  pb.front(kit.round, x, shelfTop, x + 0.05, shelfTop + h, z + 0.008);
  pb.front(kit.edge, x + w - 0.035, shelfTop, x + w, shelfTop + h, z + 0.008);
  pb.front(kit.band, x, shelfTop + 0.04, x + w, shelfTop + 0.07, z + 0.01);
  pb.front(kit.band, x, shelfTop + h - 0.095, x + w, shelfTop + h - 0.065, z + 0.01);
  const ly0 = shelfTop + 0.5 * h;
  const ly1 = shelfTop + 0.78 * h;
  pb.front(kit.label, x + 0.04, ly0, x + w - 0.04, ly1, z + 0.012);
  for (let i = 0; i < 3; i++) {
    const y = ly1 - 0.035 - i * 0.045;
    pb.front(kit.writing, x + 0.065, y, x + w - 0.065 - (i === 2 ? 0.05 : 0), y + 0.012, z + 0.014);
  }
  pb.front(kit.hole, x + w / 2 - 0.03, shelfTop + 0.26 * h, x + w / 2 + 0.03, shelfTop + 0.34 * h, z + 0.012);
  return w;
}

/**
 * One bookcase with its left edge at `x0`: a plinth, a body, a top, a dark inside, four boards with a lip, and the binders `first` to `first + count - 1` four to a
 * shelf from the bottom. A binder stands a little proud of the shelf, each at its own depth.
 */
export function bookcase(pb, t, x0, first, count) {
  const f = CASE.front;
  pb.box(t.cabBase, x0 + 0.01, 0, 0.2, 1.43, 0.1, 0.6);
  pb.box(t.cab, x0 + 0.05, 0.1, 0.2, 1.35, 2.03, 0.56);
  pb.box(t.cabTop, x0, 2.13, 0.2, 1.45, 0.07, 0.62);
  const ix0 = x0 + 0.138;
  const ix1 = x0 + 1.315;
  pb.front(t.shelfIn, ix0, 0.17, ix1, 2.06, f + 0.004);
  pb.front(t.shelfSide, ix0, 0.17, ix0 + 0.07, 2.06, f + 0.006);
  for (let k = 0; k < CASE.rows; k++) {
    const y = 0.17 + k * CASE.shelf;
    pb.front(t.shelfBoard, ix0, y, ix1, y + CASE.board, f + 0.008);
    pb.front(t.shelfLip, ix0, y + CASE.board - 0.015, ix1, y + CASE.board, f + 0.01);
  }
  let x = 0;
  for (let i = 0; i < count; i++) {
    const row = Math.floor(i / CASE.perRow);
    if (i % CASE.perRow === 0) x = x0 + 0.24;
    x += binder(pb, t, first + i, x, 0.17 + row * CASE.shelf + CASE.board) + 0.03;
  }
}

// --- the task board ------------------------------------------------------------------------------------------------------------------

export const NOTE = { w: 0.51, h: 0.53, gap: 0.13, rowGap: 0.14 };
const BOARD = { left: 0.535, right: 4.93, wall: 0.2 };

/** The right edge of the board, in page units: the bookcase stands at its right-hand end and the board is all that is left of the wall (M-7). */
export const BOARD_RIGHT = BOARD.right;

/** How many notes stand in a row of the board (it has two rows). */
const PER_ROW = Math.max(1, Math.floor((BOARD.right - 0.1 - 0.27 - NOTE.w - (BOARD.left + 0.098 + 0.1)) / (NOTE.w + NOTE.gap)) + 1);

/** How many notes the board holds: two rows of as many as stand across it. */
export const NOTE_CAPACITY = 2 * PER_ROW;

/**
 * The board of notes on the back wall: a framed panel with a shade, one note for each task of the agent in the followed request (`notes`: "done", "run" or "left"),
 * coloured by state, filling the top row from the right and then the next; a ledge with two markers and an eraser. A note has a shadow, a pin, three lines of writing
 * and a folded corner. Returns how many notes it drew.
 */
export function taskBoard(pb, t, notes) {
  const w = BOARD.wall;
  const xl = BOARD.left;
  const xr = BOARD.right;
  pb.front(t.tbFrame, xl, 0.6325, xr, 2.37, w + E);
  const px0 = xl + 0.098;
  const px1 = xr - 0.1;
  pb.front(t.tb, px0, 0.73, px1, 2.27, w + 2 * E);
  pb.front(t.tbShade, px0, 2.2, px1, 2.27, w + 3 * E);
  pb.front(t.tbShade, px1 - 0.058, 0.73, px1, 2.27, w + 3 * E);
  pb.box(t.board, xl - 0.005, 0.565, w, xr - xl, 0.07, 0.13);
  const eraser = xl + 0.24;
  pb.box(t.eraser, eraser, 0.635, w + 0.015, 0.23, 0.07, 0.08);
  for (const [back, dx] of [[t.marker, 0.795], [t.markerB, 1.29]]) {
    if (xr - dx > eraser + 0.28) pb.box(back, xr - dx, 0.635, w + 0.035, 0.31, 0.05, 0.05);
  }
  const right = px1 - 0.27;
  const per = PER_ROW;
  const shown = Math.min(notes.length, NOTE_CAPACITY);
  for (let k = 0; k < shown; k++) {
    const row = Math.floor(k / per);
    const x1 = right - (k % per) * (NOTE.w + NOTE.gap);
    const x0 = x1 - NOTE.w;
    const y1 = 2.075 - row * (NOTE.h + NOTE.rowGap) - 0.04 * (k % 2);
    const y0 = y1 - NOTE.h;
    const state = notes[k];
    const z = w + 4 * E;
    pb.front(t.noteShadow, x0 - 0.04, y0 - 0.04, x1 - 0.04, y1 - 0.04, z);
    pb.front(t.noteEdge, x0 - 0.012, y0 - 0.012, x1 + 0.012, y1 + 0.012, z + E);
    pb.front(t.note[state], x0, y0, x1, y1, z + 2 * E);
    pb.tri(t.noteFold[state], [x0, y0, z + 3 * E], [x0 + 0.125, y0, z + 3 * E], [x0, y0 + 0.125, z + 3 * E]);
    [[0.15, 1], [0.23, 1], [0.31, 0.6]].forEach(([drop, share]) => {
      pb.front(t.noteLine[state], x0 + 0.07, y1 - drop, x0 + 0.07 + (NOTE.w - 0.14) * share, y1 - drop + 0.014, z + 3 * E);
    });
    pb.front(t.notePin, x0 + 0.2, y1 - 0.11, x0 + 0.27, y1 - 0.03, z + 4 * E);
  }
  return shown;
}

// --- the desk and the chair ------------------------------------------------------------------------------------------------------------

/** Where the chair and the owl stand, in page units: the chair at the desk's near side facing it, the owl where the page puts it for each state. */
export const SEAT = Object.freeze({ chair: Object.freeze([4.8, 3.68]), owl: Object.freeze({ waiting: [3.81, 4.86], working: [4.76, 3.64], idle: [2.76, 4.44] }) });

/**
 * The agent's desk along the room's right edge: a light top on four dark legs, a drawer unit with three drawers and their handles, a keyboard with rows of keys, a mouse,
 * a sheet of paper, a mug, and a screen on a stand turned to the chair (we see its back and the logo on it).
 */
export function desk(pb, t) {
  for (const [x, z] of [[5.39, 2.73], [6.3, 2.73], [5.39, 4.73], [6.3, 4.73]]) pb.box(t.workLeg, x, 0, z, 0.1, 0.6, 0.1);
  pb.box(t.ped, 5.44, 0, 2.76, 0.79, 0.53, 0.59);
  for (let i = 0; i < 3; i++) {
    const y = 0.055 + i * 0.16;
    pb.side(t.pedDrawer, 2.83, y, 3.28, y + 0.14, 6.23 + E);
    pb.side(t.handle, 2.955, y + 0.06, 3.155, y + 0.09, 6.23 + 2 * E);
  }
  pb.box(t.work, 5.335, 0.6, 2.675, 1.12, 0.1, 2.21);
  const top = 0.7;
  pb.flat(t.paper, 5.57, 4.14, 6.04, 4.7, top + E);
  for (let i = 0; i < 4; i++) pb.flat(t.paperLine, 5.62, 4.24 + i * 0.1, 5.95 - (i === 3 ? 0.15 : 0), 4.25 + i * 0.1, top + 2 * E);
  pb.box(t.keyb, 5.475, top, 3.295, 0.31, 0.04, 0.76);
  for (let i = 0; i < 3; i++) pb.flat(t.keyLine, 5.54 + i * 0.095, 3.35, 5.55 + i * 0.095, 4.0, top + 0.04 + E);
  pb.box(t.mouse, 5.52, top, 4.15, 0.18, 0.04, 0.12);
  pb.box(t.mug, 6.035, top, 2.895, 0.17, 0.18, 0.17);
  pb.flat(t.mugIn, 6.06, 2.92, 6.18, 3.04, top + 0.18 + E);
  pb.box(t.stand, 5.98, top, 3.5, 0.28, 0.03, 0.36);
  pb.box(t.stand, 6.185, top + 0.03, 3.625, 0.06, 0.33, 0.11);
  pb.box(t.screen, 6.12, 0.845, 3.33, 0.07, 0.5, 0.7);
  pb.side(t.screenBack, 3.395, 0.9075, 3.956, 1.27, 6.19 + E);
  pb.side(t.screenLogo, 3.64, 1.0, 3.727, 1.085, 6.19 + 2 * E);
}

/** The office chair: a star base on a column, a padded seat, a back with a pad, two armrests on their posts. It faces the desk (+x). */
export function chair(pb, t) {
  const [cx, cz] = SEAT.chair;
  pb.box(t.chairBase, cx - 0.35, 0, cz - 0.05, 0.7, 0.06, 0.1);
  pb.box(t.chairBase, cx - 0.05, 0, cz - 0.35, 0.1, 0.06, 0.7);
  pb.box(t.chairBase, cx - 0.06, 0.06, cz - 0.055, 0.12, 0.31, 0.11);
  pb.box(t.chair, cx - 0.31, 0.36, cz - 0.305, 0.62, 0.11, 0.61);
  pb.flat(t.chairPad, cx - 0.25, cz - 0.25, cx + 0.25, cz + 0.25, 0.47 + E);
  pb.box(t.chairBase, cx - 0.345, 0.395, cz - 0.055, 0.08, 0.28, 0.11);
  pb.box(t.chair, cx - 0.4, 0.62, cz - 0.28, 0.1, 0.59, 0.56);
  pb.side(t.chairPad, cz - 0.21, 0.68, cz + 0.21, 1.14, cx - 0.3 + E);
  for (const dz of [-0.385, 0.285]) {
    pb.box(t.chairBase, cx - 0.035, 0.405, cz + dz, 0.07, 0.23, 0.07);
    pb.box(t.chair, cx - 0.18, 0.635, cz + dz, 0.36, 0.06, 0.08);
  }
}

// --- the Lobby's door ----------------------------------------------------------------------------------------------------------------

export const DOOR = Object.freeze({ z0: 3.18, z1: 4.8, top: 2.28 });

/** The door of the Lobby on the left wall, set into the wall: a casing, a leaf with two sunk panels and a handle. */
export function door(pb, t) {
  const x = 0.2;
  // the casing is a frame round the leaf (the leaf stands back in the wall, so a whole rectangle in front of it would cover it)
  pb.side(t.doorFrame, DOOR.z0, 0, 3.295, DOOR.top, x + E);
  pb.side(t.doorFrame, 4.695, 0, DOOR.z1, DOOR.top, x + E);
  pb.side(t.doorFrame, 3.295, 2.17, 4.695, DOOR.top, x + E);
  const leaf = x - 0.084;
  pb.side(t.door, 3.295, 0, 4.695, 2.17, leaf);
  for (const [y0, y1] of [[0.117, 0.845], [1.069, 1.867]]) {
    pb.side(t.doorShade, 3.447 - 0.02, y0 - 0.02, 4.428 + 0.02, y1 + 0.02, leaf + E);
    pb.side(t.doorPanel, 3.447, y0, 4.428, y1, leaf + 2 * E);
  }
  pb.box({ top: t.knob, left: t.knob, right: t.knob }, leaf, 0.925, 4.355, 0.04, 0.11, 0.135);
}
