// The City's ground (round 4, R-16, `scene.css` and the drawing of `city.html`): a low-poly city in flat faces. Streets with a lane line, blocks with
// a kerb and a walk, each block a paved square or a park, faceted trees (A-44: as `city.html` draws them). One block holds each project's building (at most four, in a row); the
// rest is the city round them, drawn far enough that no zoom or pan of the camera shows its edge. Nothing in it is a fact of a project and
// nothing takes a click: the buildings stand on it as towers (tower.js) and the world (world.js) puts the two together.
//
// Everything static is baked into a few batches (kit.batch) and the trees are three instanced meshes (crowns, trunks, shadows), so the ground is a handful of draw calls
// whatever the number of blocks. No colour is written here: colours come from the palette (`cityTones`, the recipes of `scene.css`).

import { beaconPulse } from "./prototype-motion.js";
import { cityTones } from "./palette.js";
import { AZIMUTH, ELEVATION } from "./rig.js";

// Sizes in world units, from the drawing (a block's walk, its paving and a street; the building's footprint is 6.4 by 4.8, building.js).
export const BLOCK_W = 11.5;                 // a block with its walk, along x
export const BLOCK_D = 14.1;                 // along z
export const PAVED_W = 10.1;                 // the paving or the grass inside the walk
export const PAVED_D = 12.7;
export const STREET = 3.3;
export const PITCH_X = BLOCK_W + STREET;     // the grid's steps
export const PITCH_Z = BLOCK_D + STREET;
export const KERB = 0.2;                     // a block's height: the floor of every building stands on it (building.js BASE)
const ABOVE = 0.01;                          // what lies on a surface stands this far over it
export const MARGIN_X = 6;                   // blocks drawn beyond the row of lots, on each side, and rows above and below it
export const ROWS = 5;
const DASH = 0.62;
const GAP = 0.72;
const LANE = 0.14;

/** The centre of the block of lot i of n: the lots stand in a row along x, centred on the origin, one block each. */
export function lotAt(i, n) {
  return { x: (i - (n - 1) / 2) * PITCH_X, z: 0 };
}

/** A repeatable pseudo-random number from 0 to 1 for three integers (the same city every time: nothing is drawn by chance). */
export function hash(a, b, c = 0) {
  let h = (Math.imul(a | 0, 374761393) + Math.imul(b | 0, 668265263) + Math.imul(c | 0, 2147483647)) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  h ^= h >>> 16;
  return (h >>> 0) / 4294967296;
}

/** What a block is: "lot" (a project's, paved), "plaza" (paved) or "park" (grass), from its place in the grid. `col` 0 is the first lot. */
export function blockKind(col, row, n) {
  if (row === 0 && col >= 0 && col < n) return "lot";
  return (((col + row) % 2) + 2) % 2 === 0 ? "plaza" : "park";
}

/** Where the trees of a block stand, as [x, z, size] from the block's centre: four at the corners of a lot, a few on a plaza, a grove on a park. */
export function treesOf(kind, col, row) {
  const hx = PAVED_W / 2 - 1.1;
  const hz = PAVED_D / 2 - 1.1;
  if (kind === "lot") return [[-hx, -hz, 1.1], [hx, -hz, 1.0], [hx, hz - 0.6, 1.05], [-hx, hz - 0.6, 1.15]];
  const count = kind === "park" ? 6 + Math.floor(hash(col, row, 1) * 3) : 3;
  const out = [];
  for (let k = 0; k < count; k++) {
    const x = (hash(col, row, 10 + k) * 2 - 1) * hx;
    const z = (hash(col, row, 40 + k) * 2 - 1) * hz;
    if (out.some(([ox, oz]) => Math.hypot(ox - x, oz - z) < 2.2)) continue;   // two on one spot are one: keep a gap
    out.push([x, z, 0.9 + hash(col, row, 70 + k) * 0.35]);
  }
  return out;
}

// A tree as `city.html` draws it (A-44, R4-B4): a trunk of two faces and a crown of about eight visible triangles in four tones lit from the upper left, over a flat
// shadow ellipse. At size 1 (the page's most common tree) the crown is 20 px across and 22.6 px tall at the City's 23.8 px to a camera unit, the trunk 5.9 px across and
// 12.6 px tall, the crown's lowest point on the trunk's top and the shadow's centre 9.5 px to the left of the trunk, which are the numbers below in world units.
export const TREE = Object.freeze({
  trunkWidth: 0.175, trunkHeight: 0.65,
  crownRadius: 0.5, crownStretch: 1.16,       // an icosahedron on a vertical axis, taller than wide as the page's is (20.1 by 22.6 px)
  shadowRadius: 0.43, shadowShift: [-0.233, 0.333],   // the ground shadow (rx 10.2 px), and where its centre lies from the trunk, in x and z, at size 1
});
const LIGHT_FROM = [-0.55, 0.7, 0.45];   // the sun of the page's trees, in the camera's own axes: right, up, toward the viewer (from the upper left, in front)
const TONE_SHARE = [1, 2, 2, 3];          // of the facets the camera sees, lightest first: `city.html` draws 1, 2, 2 and 3 of its 8

/** The sun of the trees in the world, from the camera's azimuth and elevation (the engine's rig): upper left of the picture, whatever the turn of an instance. */
export function treeLight(THREE) {
  const right = new THREE.Vector3(Math.cos(AZIMUTH), 0, -Math.sin(AZIMUTH));
  const front = new THREE.Vector3(Math.sin(AZIMUTH) * Math.cos(ELEVATION), Math.sin(ELEVATION), Math.cos(AZIMUTH) * Math.cos(ELEVATION));
  const up = new THREE.Vector3().crossVectors(front, right);
  return new THREE.Vector3().addScaledVector(right, LIGHT_FROM[0]).addScaledVector(up, LIGHT_FROM[1]).addScaledVector(front, LIGHT_FROM[2]).normalize();
}

/** A non-indexed icosahedron of circumradius 1 with a vertex up and one of its upper ring's vertices toward the camera: the facets as [a, b, c] triples of points. */
function icosahedron(THREE) {
  const ring = 2 / Math.sqrt(5);
  const height = 1 / Math.sqrt(5);
  const face = Math.PI / 4;   // the camera looks from azimuth 45 degrees: this vertex of the upper ring points at it
  const at = (angle, y) => new THREE.Vector3(ring * Math.sin(angle), y, ring * Math.cos(angle));
  const top = new THREE.Vector3(0, 1, 0);
  const bottom = new THREE.Vector3(0, -1, 0);
  const upper = [0, 1, 2, 3, 4].map((k) => at(face + (k * 2 * Math.PI) / 5, height));
  const lower = [0, 1, 2, 3, 4].map((k) => at(face + ((k + 0.5) * 2 * Math.PI) / 5, -height));
  const facets = [];
  for (let k = 0; k < 5; k++) {
    const next = (k + 1) % 5;
    facets.push([top, upper[next], upper[k]]);                // the cap
    facets.push([upper[k], upper[next], lower[k]]);           // the band, pointing up
    facets.push([lower[k], upper[next], lower[next]]);        // the band, pointing down
    facets.push([bottom, lower[k], lower[next]]);             // the foot
  }
  return facets;
}

/**
 * The facets of a crown: an icosahedron stretched to `size` (a Vector3 of half-widths) round `centre`, each {points: [a, b, c] wound outward, tone: 0 to 3 (lightest first)}. A
 * facet's tone is decided in the world, from its normal and the sun (`treeLight`): the camera's azimuth never changes and nothing that uses these facets is turned, so each facet
 * keeps the tone it was given. The facets the camera sees are ranked by the light and shared 1, 2, 2 and 3 among the four tones as `city.html` shares its eight; what the camera
 * does not see takes the darkest. The trees' crowns and the potted plants of the rooms (plants.js) are this solid.
 */
export function crownFacets(THREE, size, centre) {
  const light = treeLight(THREE);
  const toCamera = new THREE.Vector3(Math.sin(AZIMUTH) * Math.cos(ELEVATION), Math.sin(ELEVATION), Math.cos(AZIMUTH) * Math.cos(ELEVATION));
  const facets = [];
  for (const facet of icosahedron(THREE)) {
    const points = facet.map((p) => p.clone().multiply(size).add(centre));
    let normal = new THREE.Vector3().crossVectors(points[1].clone().sub(points[0]), points[2].clone().sub(points[0])).normalize();
    if (normal.dot(points[0].clone().add(points[1]).add(points[2]).divideScalar(3).sub(centre)) < 0) {   // wound inward: turn it round, so that it faces out and is drawn
      points.push(points.splice(1, 1)[0]);
      normal = normal.negate();
    }
    facets.push({ points, dot: normal.dot(light), seen: normal.dot(toCamera) > 0.01, tone: 3 });
  }
  const seen = facets.filter((f) => f.seen).sort((p, q) => q.dot - p.dot);
  const total = TONE_SHARE.reduce((a, b) => a + b, 0);
  seen.forEach((facet, rank) => {
    let share = 0;
    TONE_SHARE.some((n, k) => {
      share += n;
      if (rank < (share * seen.length) / total - 1e-9) {
        facet.tone = k;
        return true;
      }
      return false;
    });
  });
  return facets.map(({ points, tone }) => ({ points, tone }));
}

/** The crown (an icosahedron in four tones) and the trunk of a tree, as geometries painted from `tones`, and the flat shadow. */
export function treeGeometries(THREE, tones) {
  const centre = new THREE.Vector3(0, TREE.trunkHeight + TREE.crownRadius * TREE.crownStretch - 0.01, 0);
  const facets = crownFacets(THREE, new THREE.Vector3(TREE.crownRadius, TREE.crownRadius * TREE.crownStretch, TREE.crownRadius), centre);
  const position = [];
  const tone = [];
  for (const facet of facets) {
    for (const p of facet.points) position.push(p.x, p.y, p.z);
    tone.push(facet.tone);
  }
  const crown = new THREE.BufferGeometry();
  crown.setAttribute("position", new THREE.Float32BufferAttribute(position, 3));
  const colours = new Float32Array(position.length);
  tone.forEach((k, i) => { for (let v = 0; v < 3; v++) tones.crown[k].toArray(colours, (i * 3 + v) * 3); });
  crown.setAttribute("color", new THREE.BufferAttribute(colours, 3));
  // the trunk: the three faces the camera sees (the top, the +z side and the +x side), six triangles, in one tone as `city.html` draws it
  const t = TREE.trunkWidth / 2;
  const top = TREE.trunkHeight;
  const quads = [[[-t, top, t], [t, top, t], [t, top, -t], [-t, top, -t]], [[-t, 0, t], [t, 0, t], [t, top, t], [-t, top, t]], [[t, 0, t], [t, 0, -t], [t, top, -t], [t, top, t]]];
  const trunkPosition = quads.flatMap(([a, b, c, d]) => [...a, ...b, ...c, ...a, ...c, ...d]);
  const trunk = new THREE.BufferGeometry();
  trunk.setAttribute("position", new THREE.Float32BufferAttribute(trunkPosition, 3));
  trunk.setAttribute("color", new THREE.BufferAttribute(Float32Array.from({ length: trunkPosition.length }, (_, i) => tones.trunk.toArray()[i % 3]), 3));
  const shadow = new THREE.CircleGeometry(TREE.shadowRadius, 16).rotateX(-Math.PI / 2);   // flat on the ground, facing up
  return { crown, trunk, shadow, tones: tone };
}

/**
 * The ground for `n` lots. Returns {group, trees}: `group` holds the batches and the instanced trees; `trees` is how many were planted.
 * Streets and kerbs are one batch, the lane marks another, the paving and the parks a third; the trees are three instanced meshes.
 */
export function buildGround(kit, n) {
  const { THREE, palette } = kit;
  const tones = cityTones(palette);
  const group = new THREE.Group();
  const count = Math.max(1, n);
  const col0 = -MARGIN_X;
  const col1 = count - 1 + MARGIN_X;
  const gx = (col) => lotAt(0, count).x + col * PITCH_X;
  const gz = (row) => row * PITCH_Z;
  const x0 = gx(col0) - PITCH_X;
  const x1 = gx(col1) + PITCH_X;
  const z0 = gz(-ROWS) - PITCH_Z;
  const z1 = gz(ROWS) + PITCH_Z;

  const base = kit.batch();          // the road, then every block's kerb and walk
  const paving = kit.batch();        // the paved squares and the parks, on the blocks
  const lanes = kit.batch();         // the dashes of the lane lines
  base.flat(x0, z0, x1, z1, 0, tones.road);
  const planted = [];
  for (let row = -ROWS; row <= ROWS; row++) {
    for (let col = col0; col <= col1; col++) {
      const cx = gx(col);
      const cz = gz(row);
      const kind = blockKind(col, row, count);
      base.box(BLOCK_W, KERB, BLOCK_D, cx, 0, cz, { top: tones.walk, left: tones.kerb, right: tones.kerb });
      paving.flat(cx - PAVED_W / 2, cz - PAVED_D / 2, cx + PAVED_W / 2, cz + PAVED_D / 2, KERB + ABOVE, kind === "park" ? tones.grass : tones.plaza);
      for (const [dx, dz, size] of treesOf(kind, col, row)) planted.push([cx + dx, cz + dz, size]);
      // the lane line runs down the middle of each street beside the block: along x under it, along z beside it
      for (let t = -BLOCK_W / 2 + DASH / 2; t <= BLOCK_W / 2 - DASH / 2; t += DASH + GAP) {
        lanes.flat(cx + t - DASH / 2, cz + BLOCK_D / 2 + STREET / 2 - LANE / 2, cx + t + DASH / 2, cz + BLOCK_D / 2 + STREET / 2 + LANE / 2, ABOVE, tones.lane);
      }
      for (let t = -BLOCK_D / 2 + DASH / 2; t <= BLOCK_D / 2 - DASH / 2; t += DASH + GAP) {
        lanes.flat(cx + BLOCK_W / 2 + STREET / 2 - LANE / 2, cz + t - DASH / 2, cx + BLOCK_W / 2 + STREET / 2 + LANE / 2, cz + t + DASH / 2, ABOVE, tones.lane);
      }
    }
  }
  base.mesh(group, { cast: false });
  paving.mesh(group, { cast: false });
  lanes.mesh(group, { cast: false });

  const { crown, trunk, shadow } = treeGeometries(THREE, tones);
  // the ground shadow: the shadow token at the page's 9 percent in light and 42 in dark, flat, drawn over the paving and under the sun's own shadows (no real-time shadow of a tree)
  const shadowMaterial = kit.adopt(new THREE.MeshBasicMaterial({ color: tones.shadow, transparent: true, opacity: palette.dark ? 0.42 : 0.09, depthWrite: false }));
  const crowns = kit.instanced(crown, planted.length, group, { cast: false });
  const trunks = kit.instanced(trunk, planted.length, group, { cast: false });
  const shadows = kit.instanced(shadow, planted.length, group, { cast: false, material: shadowMaterial });
  const matrix = new THREE.Matrix4();
  const turn = new THREE.Quaternion();   // a tree is never turned: its facets were lit once, for the one camera
  planted.forEach(([x, z, size], i) => {
    const scale = new THREE.Vector3(size, size, size);
    matrix.compose(new THREE.Vector3(x, KERB + ABOVE, z), turn, scale);
    crowns.setMatrixAt(i, matrix);
    trunks.setMatrixAt(i, matrix);
    matrix.compose(new THREE.Vector3(x + TREE.shadowShift[0] * size, KERB + ABOVE / 2 * 3, z + TREE.shadowShift[1] * size), turn, scale);
    shadows.setMatrixAt(i, matrix);
  });
  crowns.instanceMatrix.needsUpdate = true;
  trunks.instanceMatrix.needsUpdate = true;
  shadows.instanceMatrix.needsUpdate = true;
  return { group, trees: planted.length };
}

/**
 * The beacon's pulse at `seconds`, the prototype's (prototype-motion.js `beaconPulse`): `sin(3 t)` (a 2.09 s cycle), scale 1 plus or minus .12
 * in the ring's own plane (its thickness stays), opacity .35 to .65, times the roof's fade (the ring goes with the roof while the building
 * opens). Ambient, held to 30 frames a second by the scheduler.
 */
export function pulseBeacon(beacon, seconds) {
  const pulse = beaconPulse(seconds);
  beacon.ring.scale.set(pulse.scale, pulse.scale, 1);
  beacon.material.opacity = pulse.opacity * (beacon.fade === undefined ? 1 : beacon.fade);
}

/** The beacon at rest (no ambient animation): full size and opaque (times the roof's fade). */
export function restBeacon(beacon) {
  beacon.ring.scale.set(1, 1, 1);
  beacon.material.opacity = beacon.fade === undefined ? 1 : beacon.fade;
}
