// The server room in the round's style (R-51): the room of `control-room.html`, every measure decoded off the page's own drawing (its isometric has three equal axes, so a page
// unit is the same length on x, y and z) and written here in the page's units, as `furniture.js` does for the rooms of the Building. Three racks against the left wall (a plinth, a body
// with a framed front, a grille, vents on the top and the side, a cable tray over them; seven units each: a slot with two ears, three drive bays, an activity dot and the fact's light),
// the wall screen on the back wall (a body with depth on two mounts, a bezel, the screen with a grid, a head line, a base line and a capped bar for each day, a tick under each), and
// the console (a desk on panel legs with a back panel and a drawer unit, two screens that are off on stands, a keyboard before each, a mouse, an office chair on the near side). No
// plant: it carried no fact. Each function draws into a batch of page units (`pageBatch`); a layer that stands on another is put a hair in front of it, as the page paints it over.
// The tones are `roomTones` and `serverTones` (palette.js); no colour and no name of a project is written here.

import { PAGE, pageFrame } from "./room-frame.js";

const E = 0.002;   // the distance between a layer and the one under it, in page units

/** The page's room on this scene's scale: 7 by 5.6 units across 6.4, the same on every axis (the City's rooms are 6 percent shallower; the page's server room is not). */
export const SCALE = 6.4 / 7;
/** The slab under the room, as the page draws it: it stands 0.418 out of the room on every side and 0.309 high. */
export const LEDGE = Object.freeze({ x0: -0.418, z0: -0.418, w: 7.838, d: 6.437, h: 0.309 });
export const FRAME = pageFrame({ W: 6.4, D: PAGE.d * SCALE, H: PAGE.h * SCALE, SLAB: LEDGE.h * SCALE });
/** The room: where the page's room stands against its slab. */
export const ROOM = Object.freeze({ w: PAGE.w, d: PAGE.d, h: PAGE.h, wall: PAGE.wall });

// --- the shell and the cable tray ----------------------------------------------------------------------------------------------------------

/** The slab, the floor and the two back walls (the left one and the one behind the wall screen), one batch with the tray. */
export function shell(pb, t) {
  pb.box(t.ledge, LEDGE.x0, -LEDGE.h, LEDGE.z0, LEDGE.w, LEDGE.h, LEDGE.d);
  pb.flat(t.floor, 0, 0, ROOM.w, ROOM.d, 0.004);
  pb.box(t.wall, 0, 0, 0, ROOM.w, ROOM.h, ROOM.wall);
  pb.box(t.wall, 0, 0, 0, ROOM.wall, ROOM.h, ROOM.d);
}

const TRAY = { x: 0.194, w: 0.476, z0: 0.838, z1: 4.561, y: 2.517, thick: 0.07, post: { x: 0.391, w: 0.072, d: 0.07, z: [1.007, 2.128, 3.248, 4.367] } };

/** The cable tray over the three racks: a long bar on four posts that stand on the racks' tops. */
export function tray(pb, t) {
  for (const z of TRAY.post.z) pb.box(t.tray, TRAY.post.x, RACK_TOP, z, TRAY.post.w, TRAY.y - RACK_TOP, TRAY.post.d);
  pb.box(t.tray, TRAY.x, TRAY.y, TRAY.z0, TRAY.w, TRAY.thick, TRAY.z1 - TRAY.z0);
}

// --- the racks -----------------------------------------------------------------------------------------------------------------------------

/** Three racks 1.4 apart (the z of each plinth's back edge), seven units each, a unit 0.264 above the one under it and 0.215 high. */
export const RACK = Object.freeze({ units: 7, z: Object.freeze([0.686, 2.086, 3.486]), pitch: 1.4, unitPitch: 0.264, unitHeight: 0.215, first: 0.266 });
const RACK_TOP = 2.323;   // a plinth of 0.099 and a body of 2.224
const FACE = 1.177;       // the body's front (+x), the plane the units are on

/**
 * Rack k (0 to 2): a plinth, a body, a framed front with a grille, seven units and the vents. `lights` is the fact's light of each unit from the bottom up: "ok" (found), "bad"
 * (missing) or "off" (the unit carries no fact); the first fact stands on the top unit of the first rack, which the caller says by the order it gives.
 */
export function rack(pb, t, k, lights) {
  const z0 = RACK.z[k];
  pb.box(t.rackBase, 0.24, 0, z0, 0.952, 0.099, 1.233);
  pb.box(t.rack, 0.255, 0.099, z0 + 0.015, 0.922, 2.224, 1.203);
  const zFront = z0 + 1.218;   // the body's side that faces the camera's left (+z)
  // vents on the top (five strokes along z) and on the side (two groups of six upright strokes)
  for (const x of [0.42, 0.545, 0.673, 0.798, 0.923]) pb.flat(t.ventTop, x - 0.015, z0 + 0.18, x + 0.015, z0 + 1.049, RACK_TOP + E);
  for (const x of [0.423, 0.518, 0.617, 0.716, 0.815, 0.91]) {
    for (const [y0, y1] of [[0.28, 0.7], [1.68, 2.1]]) pb.front(t.ventSide, x - 0.015, y0, x + 0.015, y1, zFront + E);
  }
  // the front: a framed panel with a grille over it, and the units on it
  pb.side(t.rackDoor, z0 + 0.063, 0.146, z0 + 1.155, 2.262, FACE + E);
  pb.side(t.grille, z0 + 0.12, 2.121, z0 + 1.099, 2.22, FACE + 2 * E);
  lights.forEach((light, u) => {
    const y = RACK.first + u * RACK.unitPitch;
    pb.side(t.unit, z0 + 0.12, y, z0 + 1.099, y + RACK.unitHeight, FACE + 2 * E);
    pb.side(t.ear, z0 + 0.12, y, z0 + 0.174, y + RACK.unitHeight, FACE + 3 * E);
    pb.side(t.ear, z0 + 1.042, y, z0 + 1.099, y + RACK.unitHeight, FACE + 3 * E);
    for (const [a, b] of [[0.231, 0.386], [0.413, 0.566], [0.596, 0.748]]) pb.side(t.bay, z0 + a, y + 0.05, z0 + b, y + 0.167, FACE + 3 * E);
    pb.side(t.ledDim, z0 + 0.706, y + 0.083, z0 + 0.763, y + 0.13, FACE + 4 * E);
    const tone = light === "ok" ? t.ledOk : light === "bad" ? t.ledBad : t.ledOff;
    pb.side(tone, z0 + 0.82, y + 0.065, z0 + 0.988, y + 0.154, FACE + 4 * E);
  });
}

// --- the wall screen -----------------------------------------------------------------------------------------------------------------------

/** Seven bar slots 0.4 apart from x 2.879, each 0.26 wide and up to 0.925 high from the base line, a cap 0.05 high on each bar and a tick under each slot. */
export const SCREEN = Object.freeze({ slots: 7, first: 2.879, pitch: 0.4, barWidth: 0.26, full: 0.925, base: 1.073, cap: 0.05, front: 0.311 });

/** Dashes of a line along x at height y on the plane z, `width` thick: the page's dashed strokes (`stroke-dasharray`). */
function dashed(pb, tone, x0, x1, y, width, dash, gap, z) {
  for (let x = x0; x < x1 - 1e-6; x += dash + gap) pb.front(tone, x, y - width / 2, Math.min(x + dash, x1), y + width / 2, z);
}

/**
 * The wall screen: two mounts, a body with depth, a bezel, the screen with its grid, its head line and its base line, a light, a bar for each day with runs (`bars`: seven shares
 * of the largest day from 0 to 1; a day with none draws none) with a lighter cap, and a tick under each of the seven days.
 */
export function wallScreen(pb, t, bars) {
  const z = SCREEN.front;
  for (const x of [3.363, 4.874]) pb.box(t.mount, x, 1.29, 0.2, 0.168, 0.56, 0.042);
  pb.box(t.body, 2.565, 0.772, 0.242, 3.304, 1.626, 0.069);
  pb.front(t.bezel, 2.565, 0.772, 5.869, 2.398, z + E);
  pb.front(t.wsScreen, 2.669, 0.878, 5.749, 2.278, z + 2 * E);
  for (const y of [1.379, 1.682, 1.999]) dashed(pb, t.wsGrid, 2.81, 5.608, y, 0.02, 0.052, 0.052, z + 3 * E);
  pb.front(t.wsLine, 2.81, 2.152 - 0.013, 3.72, 2.152 + 0.013, z + 3 * E);
  pb.front(t.wsLine, 2.81, SCREEN.base - 0.013, 5.608, SCREEN.base + 0.013, z + 3 * E);
  pb.front(t.wsLed, 5.608, 0.792, 5.692, 0.842, z + 3 * E);
  for (let i = 0; i < SCREEN.slots; i++) {
    const x = SCREEN.first + i * SCREEN.pitch;
    const share = Math.max(0, Math.min(1, bars[i] || 0));
    if (share > 0) {
      const top = SCREEN.base + SCREEN.full * share;
      pb.front(t.bar, x, SCREEN.base, x + SCREEN.barWidth, top, z + 4 * E);
      pb.front(t.barCap, x, Math.max(SCREEN.base, top - SCREEN.cap), x + SCREEN.barWidth, top, z + 5 * E);
    }
    pb.front(t.wsLine, x + 0.08, 0.99 - 0.013, x + 0.18, 0.99 + 0.013, z + 3 * E);
  }
}

// --- the console ---------------------------------------------------------------------------------------------------------------------------

const DESK = { x: 3.277, z: 2.717, w: 2.939, d: 1.287, top: 0.754, thick: 0.086 };
const SCREENS = [{ x: 3.6315, w: 1.009, stand: { x: 3.909, w: 0.446, stem: 4.0805, stemW: 0.111, h: 0.034 }, face: [3.674, 4.584, 1.119, 1.657],
  glint: [[3.764, 1.656], [3.988, 1.657], [3.794, 1.259], [3.674, 1.259], [3.674, 1.497]], keys: { x: 3.767, z: 3.486, w: 0.7, d: 0.281, lines: [3.54, 3.605, 3.668, 3.73], from: 3.809, to: 4.425 } },
{ x: 4.8645, w: 1.006, stand: { x: 5.137, w: 0.449, stem: 5.313, stemW: 0.114, h: 0.036 }, face: [4.907, 5.817, 1.118, 1.659],
  glint: [[4.997, 1.658], [5.221, 1.656], [5.024, 1.257], [4.907, 1.258], [4.907, 1.497]], keys: { x: 4.998, z: 3.487, w: 0.7, d: 0.278, lines: [3.541, 3.603, 3.668, 3.731], from: 5.04, to: 5.655 } }];
const SCREEN_Y = 1.07;
const SCREEN_Z = { z: 3.0725, d: 0.069 };

/**
 * The console: a desk on two panel legs with a back panel and a drawer unit (three drawers and their handles), two screens that are off on stands with a keyboard before each (rows of
 * keys), a mouse between the keyboards, and an office chair on the near side (+z) with its back to the camera: a star base on a column, a padded seat, a back with a pad, two armrests.
 */
export function consoleDesk(pb, t) {
  const top = DESK.top + DESK.thick;
  pb.box(t.workLeg, 3.4875, 0, 2.8685, 0.096, DESK.top, 1.149);
  pb.box(t.workLeg, 6.08, 0, 2.8685, 0.099, DESK.top, 1.149);
  pb.box(t.workBack, 3.5445, 0, 2.9255, 2.574, DESK.top, 0.072);
  pb.box(t.ped, 5.3075, 0, 2.9275, 0.7, DESK.top, 0.979);
  const zf = 2.9275 + 0.979;
  [[0.066, 0.261], [0.305, 0.499], [0.541, 0.738]].forEach(([y0, y1], i) => {
    pb.front(t.pedDrawer, 5.373, y0, 5.933, y1, zf + E);
    const h = [[0.146, 0.175], [0.385, 0.412], [0.623, 0.65]][i];
    pb.front(t.handle, 5.538, h[0], 5.762, h[1], zf + 2 * E);
  });
  pb.box(t.work, DESK.x, DESK.top, DESK.z, DESK.w, DESK.thick, DESK.d);
  for (const s of SCREENS) {
    pb.box(t.stand, s.stand.x, top, 2.955, s.stand.w, s.stand.h, 0.281);
    pb.box(t.stand, s.stand.stem, top + s.stand.h, 3.0275, s.stand.stemW, 0.28, 0.072);
    pb.box(t.screen, s.x, SCREEN_Y, SCREEN_Z.z, s.w, 0.643, SCREEN_Z.d);
    const zs = SCREEN_Z.z + SCREEN_Z.d;
    pb.front(t.screenFace, s.face[0], s.face[2], s.face[1], s.face[3], zs + E);
    const g = s.glint.map(([x, y]) => [x, y, zs + 2 * E]);
    for (let k = 1; k < g.length - 1; k++) pb.tri(t.glint, g[0], g[k + 1], g[k]);   // the page lists the corners clockwise; a face is drawn counter-clockwise
    const kb = s.keys;
    pb.box(t.keyb, kb.x, top, kb.z, kb.w, 0.036, kb.d);
    for (const z of kb.lines) {
      for (let x = kb.from; x < kb.to - 1e-6; x += 0.068) pb.flat(t.keyLine, x, z - 0.013, Math.min(x + 0.042, kb.to), z + 0.013, top + 0.036 + E);
    }
  }
  pb.box(t.mouse, 4.6755, top, 3.5565, 0.114, 0.041, 0.168);
  // the chair: it faces the desk (-z), so the camera sees its back
  pb.box(t.chairBase, 3.9495, 0, 4.67, 0.7, 0.057, 0.096);
  pb.box(t.chairBase, 4.25, 0, 4.37, 0.099, 0.057, 0.697);
  pb.box(t.chairBase, 4.245, 0.057, 4.664, 0.111, 0.306, 0.111);
  pb.box(t.chair, 3.991, 0.366, 4.41, 0.617, 0.114, 0.617);
  pb.flat(t.chairPad, 4.066, 4.485, 4.541, 4.96, 0.48 + E);
  pb.box(t.chairBase, 4.2425, 0.393, 4.9995, 0.114, 0.283, 0.069);
  pb.box(t.chair, 4.0195, 0.6155, 5.0255, 0.56, 0.589, 0.099);
  pb.front(t.chairPad, 4.086, 0.698, 4.508, 1.119, 5.1245 + E);
  for (const [x, z] of [[3.955, 4.5515], [4.5735, 4.5525]]) pb.box(t.chairBase, x, 0.4215, z, 0.072, 0.223, 0.069);
  for (const x of [3.922, 4.593]) pb.box(t.chair, x, 0.6445, 4.551, 0.084, 0.054, 0.365);
}

// --- the corner brackets of an object (R-51) -------------------------------------------------------------------------------------------------

/**
 * Where the corners stand, read off the page's own marks: one box round the three racks and one round the desk and its chair (an arm of 0.42 along each edge, a short line down at
 * each top corner and one up at each base corner), and four corners in the back wall's plane round the wall screen.
 */
export const BRACKETS = Object.freeze({
  racks: Object.freeze({ x0: 0.224, x1: 1.327, z0: 0.56, z1: 4.855, y0: 0, y1: 2.66, arm: 0.42, drop: 0.42, rise: 0.42 }),
  console: Object.freeze({ x0: 3.225, x1: 6.42, z0: 2.725, z1: 5.135, y0: 0, y1: 1.84, arm: 0.42, drop: 0.42, rise: 0.42 }),
  wall: Object.freeze({ plane: "z", at: SCREEN.front + 0.02, a0: 2.391, a1: 6.03, y0: 0.598, y1: 2.559, arm: 0.392 }),
});
