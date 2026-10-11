// The two potted plants of a room (A-45, M-6): a dark pot, a tapered six-sided cylinder, and a crown, one icosahedron lit as the City's trees are (city.js
// `crownFacets`, the same solid and the same four tones). They stand on the floor against the left wall, the one with the windows, one near each end of the
// run of windows, clear of the room's three ways in (the owl, the board of notes, the bookcase) and of the Lobby's door. They are decoration: never picked,
// never animated, casting no shadow. The server room has none (R-51).
// The plants are not in the room's still mesh (M-16): a plant's crown stands past the shell's outer face, so it must not show while the walls close in. The tower draws all
// its plants as one instanced mesh (`tower.plants`, tower.js), two for each room, each scaled from nothing to its size as the building opens and back as it closes: nothing of a room
// shows through a closed or closing shell. The measures are page units (room-frame.js); the pot and the crown are the earlier prototype's, a little larger against this room.

import { crownFacets } from "./city.js";
import { AZIMUTH } from "./rig.js";

const FOOT = 0.012;   // the pot's foot stands a hair over the floor (the floor is at 0.004)
export const POT = Object.freeze({ top: 0.165, base: 0.125, height: 0.27, sides: 6 });
export const CROWN = Object.freeze({ radius: 0.29, stretch: 1.1, centre: 0.53 });
/** Where the plants stand on the floor, [x, z] in page units: against the left wall, at the first window's end and past the last window (the Lobby's door fills the place of the second window, and a plant in front of it would cover it, so the second stands in the front corner). */
export const PLANTS = Object.freeze([Object.freeze([0.45, 1.1]), Object.freeze([0.4, 5.45])]);

/**
 * One plant as a geometry with a colour on every vertex, its foot centre at the origin and its measures in the world units of the frame `f` (room-frame.js `pageFrame`).
 * `tones` is `roomTones(palette)`: its `pot` (a solid: top, left, right) and its `crown` (the four tones of the trees).
 */
export function plantGeometry(THREE, f, tones) {
  const position = [];
  const colour = [];
  const tri = (a, b, c, tone) => {
    for (const p of [a, b, c]) {
      position.push(p[0], p[1], p[2]);
      colour.push(tone.r, tone.g, tone.b);
    }
  };
  const toCamera = [Math.sin(AZIMUTH), Math.cos(AZIMUTH)];
  const at = (dx, y, dz) => [dx * f.sx, y * f.sy, dz * f.sz];
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
    const tone = out[1] > out[0] ? tones.pot.left : tones.pot.right;
    tri(low[k], low[next], high[next], tone);
    tri(low[k], high[next], high[k], tone);
  }
  for (let k = 1; k < POT.sides - 1; k++) tri(high[0], high[k], high[k + 1], tones.pot.top);
  // the crown: the trees' solid, sitting on the pot; its tones are decided in the world, so it is lit from the upper left like a tree
  const size = new THREE.Vector3(CROWN.radius * f.sx, CROWN.radius * CROWN.stretch * f.sy, CROWN.radius * f.sx);
  const centre = new THREE.Vector3(0, CROWN.centre * f.sy, 0);
  for (const facet of crownFacets(THREE, size, centre)) tri(...facet.points.map((p) => [p.x, p.y, p.z]), tones.crown[facet.tone]);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(position, 3));
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colour, 3));
  geometry.computeBoundingSphere();
  return geometry;
}
