// The two potted plants of a room (A-45, M-6): a dark pot, a tapered six-sided cylinder, and a crown, one icosahedron lit as the City's trees are (city.js
// `crownFacets`, the same solid and the same four tones). They stand on the floor against the left wall, the one with the windows, one near each end of the
// run of windows, clear of the room's three ways in (the owl, the board of notes, the bookcase) and of the Lobby's door. They are decoration: baked into the room's
// still batch (no draw call of their own), never picked, never animated, and they cast no shadow. The server room has none (R-51).
// The measures are page units (room-frame.js); the pot and the crown are the earlier prototype's, a little larger against this room.

import { crownFacets } from "./city.js";
import { AZIMUTH } from "./rig.js";

const FOOT = 0.012;   // the pot's foot stands a hair over the floor (the floor is at 0.004), so that the floor's own tone stays what the floor's vertices say
export const POT = Object.freeze({ top: 0.165, base: 0.125, height: 0.27, sides: 6 });
export const CROWN = Object.freeze({ radius: 0.29, stretch: 1.1, centre: 0.53 });
/** Where the plants stand on the floor, [x, z] in page units: against the left wall, at the first window's end and past the last window (the Lobby's door fills the place of the second window, and a plant in front of the door would cover it, so the second stands in the front corner). */
export const PLANTS = Object.freeze([Object.freeze([0.45, 1.1]), Object.freeze([0.4, 5.45])]);

/**
 * Draw the two plants into `pb` (a page batch, room-frame.js `pageBatch`) of the frame `f`. `tones` is `roomTones(palette)`: its `pot` (a solid: top, left, right) and its
 * `crown` (the four tones of the trees); `places` are the [x, z] of the plants (two, by default). Returns how many triangles it drew.
 */
export function plants(THREE, pb, f, tones, places = PLANTS) {
  const batch = pb.raw;
  const before = batch.count();
  const toCamera = [Math.sin(AZIMUTH), Math.cos(AZIMUTH)];
  for (const [px, pz] of places) {
    const at = (dx, y, dz) => [f.X(px + dx), f.Y(y), f.Z(pz + dz)];
    // the pot: six sides from the base to the rim, the ones the camera sees, and the rim's top
    const ring = (radius, y) => Array.from({ length: POT.sides }, (_, k) => {
      const angle = (k * 2 * Math.PI) / POT.sides + Math.PI / POT.sides;
      return at(radius * Math.sin(angle), y, radius * Math.cos(angle));
    });
    const low = ring(POT.base, FOOT);
    const high = ring(POT.top, FOOT + POT.height);
    for (let k = 0; k < POT.sides; k++) {
      const next = (k + 1) % POT.sides;
      const angle = ((k + 0.5) * 2 * Math.PI) / POT.sides + Math.PI / POT.sides;   // the side's outward direction
      const out = [Math.sin(angle), Math.cos(angle)];
      if (out[0] * toCamera[0] + out[1] * toCamera[1] <= 0.05) continue;
      batch.quad(low[k], low[next], high[next], high[k], out[1] > out[0] ? tones.pot.left : tones.pot.right);
    }
    for (let k = 1; k < POT.sides - 1; k++) batch.tri(high[0], high[k], high[k + 1], tones.pot.top);
    // the crown: the trees' solid, sitting on the pot; its tones are decided in the world, so it is lit from the upper left like a tree
    const size = new THREE.Vector3(CROWN.radius * f.sx, CROWN.radius * CROWN.stretch * f.sy, CROWN.radius * f.sx);
    const centre = new THREE.Vector3(f.X(px), f.Y(CROWN.centre), f.Z(pz));
    for (const facet of crownFacets(THREE, size, centre)) batch.tri(...facet.points.map((p) => [p.x, p.y, p.z]), tones.crown[facet.tone]);
  }
  return batch.count() - before;
}
