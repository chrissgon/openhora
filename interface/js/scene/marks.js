// The marks the City puts on a building (round 4): the decision mark (R-20) and the corner brackets of the building the person follows or points at
// (R-17). Both are flat-faced solids in tokens (`cityTones`), no text and no glow; the brackets are drawn in the brand colour.

import { cityTones } from "./palette.js";

// The decision mark: a small amber exclamation, a bar over a cube, as the drawing has it (a bar 0.8 over a cube 0.26 with a gap of 0.13 at the
// drawing's scale), a little larger so that it reads: a floor of the closed City is 1.9 units high and the mark is a little over two thirds of it.
// A-60, M-18: the maintainer found it too big: it is drawn at 70 percent of what R-20's first build drew, from the one constant below; its place beside the floor, its motion and its colour are the same.
export const MARK_SCALE = 0.7;
export const MARK = Object.freeze({ cube: 0.32 * MARK_SCALE, gap: 0.16 * MARK_SCALE, bar: Object.freeze([0.32 * MARK_SCALE, 0.96 * MARK_SCALE, 0.32 * MARK_SCALE]) });
export const MARK_HEIGHT = MARK.cube + MARK.gap + MARK.bar[1];

/**
 * The decision mark as a group whose origin is the middle of its foot (so it rises and tilts about its foot), added to `parent` at (x, y, z).
 * The cube and the bar are one batch in three tones: top, left and right.
 */
export function decisionMark(kit, parent, x, y, z) {
  const { THREE, palette } = kit;
  const tones = cityTones(palette).mark;
  const group = new THREE.Group();
  group.position.set(x, y, z);
  group.userData.mark = true;
  const batch = kit.batch();
  batch.box(MARK.cube, MARK.cube, MARK.cube, 0, 0, 0, tones);
  batch.box(MARK.bar[0], MARK.bar[1], MARK.bar[2], 0, MARK.cube + MARK.gap, 0, tones);
  batch.mesh(group, { cast: false });
  parent.add(group);
  return group;
}

// The brackets: an L at each of four corners, arms of ARM along both sides, ARM_WIDTH wide. On the ground they stand round the lot (the drawing:
// 8.96 by 8.64, a little toward the front); at the roof they stand round the roof's edge, each with a short line down.
const ARM = 1.15;
const ARM_WIDTH = 0.13;
const DROP = 0.9;
const GROUND_HALF = { x: 4.5, z: 4.35 };
const GROUND_SHIFT = { x: 0.3, z: 0.75 };
const ROOF_HALF = { x: 3.9, z: 3.4 };
const FLAT = 0.04;

/**
 * Eight corner brackets in the brand colour. Returns {group, roof}: `group` holds the four on the ground (at `ground` height) and `roof`, a group
 * to be moved to the roof's height, the four at the roof with their line down. Both are one batch each; the whole is hidden until asked for.
 * The positions are relative to the building's centre: the group goes where the building stands.
 */
export function bracketSet(kit, ground = 0.22) {
  const { THREE, palette } = kit;
  const colour = cityTones(palette).bracket;
  const group = new THREE.Group();
  group.visible = false;
  const roof = new THREE.Group();
  group.add(roof);
  const onGround = kit.batch();
  const atRoof = kit.batch();
  for (const sx of [-1, 1]) {
    for (const sz of [-1, 1]) {
      // an L: one arm along x and one along z from the corner (cx, cz), toward the middle
      const L = (batch, cx, cz, y) => {
        batch.box(ARM, FLAT, ARM_WIDTH, cx - sx * (ARM / 2 - ARM_WIDTH / 2), y, cz, colour);
        batch.box(ARM_WIDTH, FLAT, ARM, cx, y, cz - sz * (ARM / 2 - ARM_WIDTH / 2), colour);
      };
      L(onGround, sx * GROUND_HALF.x + GROUND_SHIFT.x, sz * GROUND_HALF.z + GROUND_SHIFT.z, ground);
      const rx = sx * ROOF_HALF.x;
      const rz = sz * ROOF_HALF.z;
      L(atRoof, rx, rz, 0.02);
      atRoof.box(ARM_WIDTH, DROP, ARM_WIDTH, rx, 0.02 - DROP, rz, colour);
    }
  }
  onGround.mesh(group, { cast: false });
  atRoof.mesh(roof, { cast: false });
  return { group, roof };
}

// --- the brackets of a picked object and of a room (R-28, R-31) ----------------------------------------------------------------------------
// The City's mark of a selected building, on a room or an object of a room: four corners round its base and four at its top, each of those with a short line down,
// drawn as real solids so that the depth hides a corner behind the object and the floor above hides one under its slab. A flat object, the task board and the door, takes
// four corners in the plane it stands in. They are made in page units (room-frame.js) in the brand colour and hidden until the engine shows them.

const BRACKET_WIDTH = 0.1;
const LIFT = 0.03;

/**
 * Eight brackets round the box x0..x1, z0..z1, y0..y1 (page units): an L at each base corner, and at each top corner an L with a line `drop` down. `arm` is how far an
 * arm runs along an edge. `rise` (R-51, the server room's racks and console) adds a short line up from each base corner, as the page draws them; the rooms of the Building and
 * the Floor leave it off. `makeBatch` wraps a batch in page units (`pageBatch`). Returns one mesh (unlit, in `tone`) for the caller to put in a hidden group; the engine shows it.
 */
export function boxBrackets(kit, makeBatch, { x0, x1, z0, z1, y0, y1, arm, drop, rise = 0, tone }) {
  const batch = kit.batch();
  const pb = makeBatch(batch);
  const w = BRACKET_WIDTH;
  for (const sx of [-1, 1]) {
    for (const sz of [-1, 1]) {
      const cx = sx < 0 ? x0 : x1;
      const cz = sz < 0 ? z0 : z1;
      for (const [y, down, up] of [[y0 + LIFT, 0, rise], [y1, drop, 0]]) {
        // an L: one arm along x and one along z, from the corner toward the middle
        pb.flat(tone, sx < 0 ? cx - w / 2 : cx - arm, cz - w / 2, sx < 0 ? cx + arm : cx + w / 2, cz + w / 2, y);
        pb.flat(tone, cx - w / 2, sz < 0 ? cz - w / 2 : cz - arm, cx + w / 2, sz < 0 ? cz + arm : cz + w / 2, y);
        if (down) pb.box(tone, cx - w / 2, y - down, cz - w / 2, w, down, w);
        if (up) pb.box(tone, cx - w / 2, y, cz - w / 2, w, up, w);
      }
    }
  }
  return batch.mesh(new kit.THREE.Group(), { cast: false });
}

/**
 * Four corners round a rectangle standing in a wall: the back wall (`plane: "z"`, at z) or the left wall (`plane: "x"`, at x), from a0..a1 along the wall and y0..y1 up it;
 * each corner has an arm along the wall and an arm up. Returns one mesh, as `boxBrackets` does.
 */
export function planeBrackets(kit, makeBatch, { plane, at, a0, a1, y0, y1, arm, tone }) {
  const batch = kit.batch();
  const pb = makeBatch(batch);
  const w = BRACKET_WIDTH;
  const rect = plane === "z" ? (u0, v0, u1, v1) => pb.front(tone, u0, v0, u1, v1, at) : (u0, v0, u1, v1) => pb.side(tone, u0, v0, u1, v1, at);
  for (const [u, du] of [[a0, 1], [a1, -1]]) {
    for (const [v, dv] of [[y0, 1], [y1, -1]]) {
      rect(Math.min(u, u + du * arm), Math.min(v, v + dv * w), Math.max(u, u + du * arm), Math.max(v, v + dv * w));
      rect(Math.min(u, u + du * w), Math.min(v, v + dv * arm), Math.max(u, u + du * w), Math.max(v, v + dv * arm));
    }
  }
  return batch.mesh(new kit.THREE.Group(), { cast: false });
}
