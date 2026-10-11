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
  // F1-D1: a park of city.html holds 8 to 12 trees and a plaza 2 to 4, scattered over the block. The block is a grid of cells (3 across, 4 deep), `count` of them chosen by a seeded order
  // and a tree stands in each, moved off the cell's middle by a seeded amount: an even scatter (two never within a metre of each other) where the plain draw of a spot put the trees of a park in a band
  const count = kind === "park" ? 9 + Math.floor(hash(col, row, 1) * 4) : 2 + Math.floor(hash(col, row, 2) * 3);
  const across = 3;
  const deep = 4;
  const cells = Array.from({ length: across * deep }, (_, k) => k).sort((p, q) => hash(col, row, 100 + p) - hash(col, row, 100 + q)).slice(0, count);
  const out = [];
  for (const k of cells) {
    const x = -hx + ((k % across) + 0.5 + (hash(col, row, 200 + k) - 0.5) * 0.7) * ((2 * hx) / across);
    const z = -hz + ((Math.floor(k / across) + 0.5 + (hash(col, row, 300 + k) - 0.5) * 0.7)) * ((2 * hz) / deep);
    out.push([x, z, 0.9 + hash(col, row, 70 + k) * 0.35]);
  }
  return out;
}

// A tree as `city.html` draws it (A-44, R4-B4) with the variety and the trunk the maintainer asked for (A-55, M-14): a crown of about eight visible triangles in four tones lit from the
// upper left (here an icosahedron in one of four variants), over a flat shadow ellipse. At size 1 (the page's most common tree) the crown is 20 px across and 22.6 px tall at the City's
// 23.8 px to a camera unit and the shadow's centre 9.5 px to the left of the trunk, which are the numbers below in world units; the trunk is thinner than the page's 5.9 px, a thin
// six-sided column 3 to 5 px across and 12.6 px tall, narrower at the top, with its top hidden in the crown.
export const TREE = Object.freeze({
  trunkFoot: 0.085, trunkTop: 0.058, trunkHeight: 0.65, trunkSides: 6,   // a thin trunk, a little tapered (M-14), the earlier look: six sides, wider at the foot, its top hidden in the crown
  crownRadius: 0.5, crownStretch: 1.16,       // an icosahedron on a vertical axis, taller than wide as the page's is (20.1 by 22.6 px)
  shadowRadius: 0.43, shadowShift: [-0.233, 0.333],   // the ground shadow (rx 10.2 px), and where its centre lies from the trunk, in x and z, at size 1
  width: [0.9, 1.1], height: [0.9, 1.15],      // the variation of one tree from the next (M-14): its width and its height against its size, seeded
});
/**
 * The crown variants (M-14): variant 0 is the icosahedron as it was (the plants' too); each other is turned about the vertical axis by `yaw` and has its twelve vertices
 * moved by up to `jitter` of the radius, seeded by the variant and the vertex, never by chance at run time. The tones of a variant are decided after the turn and the
 * move, in the world, so the sun stays at the upper left on every tree.
 */
export const VARIANTS = Object.freeze([{ yaw: 0, jitter: 0 }, { yaw: 0.52, jitter: 0.07 }, { yaw: 1.05, jitter: 0.09 }, { yaw: 1.62, jitter: 0.06 }].map(Object.freeze));
const LIGHT_FROM = [-0.55, 0.7, 0.45];   // the sun of the page's trees, in the camera's own axes: right, up, toward the viewer (from the upper left, in front)
const TONE_SHARE = [1, 2, 2, 3];          // of the facets the camera sees, lightest first: `city.html` draws 1, 2, 2 and 3 of its 8

/** The sun of the trees in the world, from the camera's azimuth and elevation (the engine's rig): upper left of the picture, whatever the turn of an instance. */
export function treeLight(THREE) {
  const right = new THREE.Vector3(Math.cos(AZIMUTH), 0, -Math.sin(AZIMUTH));
  const front = new THREE.Vector3(Math.sin(AZIMUTH) * Math.cos(ELEVATION), Math.sin(ELEVATION), Math.cos(AZIMUTH) * Math.cos(ELEVATION));
  const up = new THREE.Vector3().crossVectors(front, right);
  return new THREE.Vector3().addScaledVector(right, LIGHT_FROM[0]).addScaledVector(up, LIGHT_FROM[1]).addScaledVector(front, LIGHT_FROM[2]).normalize();
}

/**
 * A non-indexed icosahedron of circumradius 1 with a vertex up and one of its upper ring's vertices toward the camera, turned by the variant's yaw and with its vertices moved
 * by the variant's seeded jitter: the facets as [a, b, c] triples of points.
 */
function icosahedron(THREE, variant = 0) {
  const { yaw, jitter } = VARIANTS[variant];
  const ring = 2 / Math.sqrt(5);
  const height = 1 / Math.sqrt(5);
  const face = Math.PI / 4 + yaw;   // the camera looks from azimuth 45 degrees: this vertex of the upper ring points at it, before the variant's turn
  const moved = (v, index) => (jitter ? v.add(new THREE.Vector3(hash(variant * 16 + index, 1) - 0.5, hash(variant * 16 + index, 2) - 0.5, hash(variant * 16 + index, 3) - 0.5).multiplyScalar(2 * jitter)) : v);
  const at = (angle, y, index) => moved(new THREE.Vector3(ring * Math.sin(angle), y, ring * Math.cos(angle)), index);
  const top = moved(new THREE.Vector3(0, 1, 0), 0);
  const bottom = moved(new THREE.Vector3(0, -1, 0), 1);
  const upper = [0, 1, 2, 3, 4].map((k) => at(face + (k * 2 * Math.PI) / 5, height, 2 + k));
  const lower = [0, 1, 2, 3, 4].map((k) => at(face + ((k + 0.5) * 2 * Math.PI) / 5, -height, 7 + k));
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
 * does not see takes the darkest. The trees' crowns (one of the `VARIANTS`) and the potted plants of the rooms (plants.js, variant 0) are this solid.
 */
export function crownFacets(THREE, size, centre, variant = 0) {
  const light = treeLight(THREE);
  const toCamera = new THREE.Vector3(Math.sin(AZIMUTH) * Math.cos(ELEVATION), Math.sin(ELEVATION), Math.cos(AZIMUTH) * Math.cos(ELEVATION));
  const facets = [];
  for (const facet of icosahedron(THREE, variant)) {
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

/**
 * What one tree is, seeded by where it stands (the same city every time): which crown variant, and how wide and how tall it is against its size (M-14). `a`, `b` and `c` are the
 * block's column, its row and a number that tells the trees of a block apart.
 */
export function treeLook(a, b, c) {
  const within = ([lo, hi], t) => lo + (hi - lo) * t;
  return { variant: Math.min(VARIANTS.length - 1, Math.floor(hash(a, b, 200 + c) * VARIANTS.length)), width: within(TREE.width, hash(a, b, 300 + c)), height: within(TREE.height, hash(a, b, 400 + c)) };
}

/**
 * The crowns (one icosahedron in four tones for each of the `VARIANTS`), the trunk of a tree and its flat shadow, as geometries painted from `tones`. The trunk is a thin
 * six-sided column, a little narrower at the top, with the three sides the camera sees (six triangles): the side the sun reaches is the bark, the others a step darker.
 */
export function treeGeometries(THREE, tones) {
  const centre = new THREE.Vector3(0, TREE.trunkHeight + TREE.crownRadius * TREE.crownStretch - 0.01, 0);
  const size = new THREE.Vector3(TREE.crownRadius, TREE.crownRadius * TREE.crownStretch, TREE.crownRadius);
  const crowns = VARIANTS.map((variant, index) => {
    const position = [];
    const tone = [];
    for (const facet of crownFacets(THREE, size, centre, index)) {
      for (const p of facet.points) position.push(p.x, p.y, p.z);
      tone.push(facet.tone);
    }
    const crown = new THREE.BufferGeometry();
    crown.setAttribute("position", new THREE.Float32BufferAttribute(position, 3));
    const colours = new Float32Array(position.length);
    tone.forEach((k, i) => { for (let v = 0; v < 3; v++) tones.crown[k].toArray(colours, (i * 3 + v) * 3); });
    crown.setAttribute("color", new THREE.BufferAttribute(colours, 3));
    crown.userData.tones = tone;
    return crown;
  });
  const toCamera = new THREE.Vector3(Math.sin(AZIMUTH) * Math.cos(ELEVATION), Math.sin(ELEVATION), Math.cos(AZIMUTH) * Math.cos(ELEVATION));
  const light = treeLight(THREE);
  const sides = [];
  for (let k = 0; k < TREE.trunkSides; k++) {
    const middle = AZIMUTH + (k * 2 * Math.PI) / TREE.trunkSides;   // one side faces the camera, the others turn from it
    const half = Math.PI / TREE.trunkSides;
    const ring = (radius, y, angle) => [radius * Math.sin(angle), y, radius * Math.cos(angle)];
    const low = [ring(TREE.trunkFoot, 0, middle - half), ring(TREE.trunkFoot, 0, middle + half)];
    const high = [ring(TREE.trunkTop, TREE.trunkHeight, middle - half), ring(TREE.trunkTop, TREE.trunkHeight, middle + half)];
    const normal = new THREE.Vector3(Math.sin(middle), (TREE.trunkFoot - TREE.trunkTop) / TREE.trunkHeight, Math.cos(middle)).normalize();
    if (normal.dot(toCamera) > 0.02) sides.push({ low, high, dot: normal.dot(light) });
  }
  sides.sort((p, q) => q.dot - p.dot);
  const trunkPosition = [];
  const trunkColour = [];
  sides.forEach(({ low, high }, rank) => {
    const tone = rank === 0 ? tones.trunk : tones.trunkShade;   // the side the sun reaches most is the bark, the others a step darker
    for (const p of [low[0], low[1], high[1], low[0], high[1], high[0]]) {
      trunkPosition.push(...p);
      trunkColour.push(tone.r, tone.g, tone.b);
    }
  });
  const trunk = new THREE.BufferGeometry();
  trunk.setAttribute("position", new THREE.Float32BufferAttribute(trunkPosition, 3));
  trunk.setAttribute("color", new THREE.Float32BufferAttribute(trunkColour, 3));
  const shadow = new THREE.CircleGeometry(TREE.shadowRadius, 16).rotateX(-Math.PI / 2);   // flat on the ground, facing up
  return { crown: crowns[0], crowns, trunk, shadow, tones: crowns[0].userData.tones };
}

/**
 * The ground for `n` lots. Returns {group, trees}: `group` holds the batches and the instanced trees; `trees` is how many were planted.
 * Streets and kerbs are one batch, the lane marks another, the paving and the parks a third; the trees are instanced meshes (a crown for each variant, one trunk, one shadow).
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
      treesOf(kind, col, row).forEach(([dx, dz, size], k) => planted.push([cx + dx, cz + dz, size, treeLook(col, row, k)]));   // a tree's look is seeded by its place in its block: two trees of a block never share one
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

  const { crowns: crownGeometries, trunk, shadow } = treeGeometries(THREE, tones);
  // the ground shadow: the shadow token at the page's 9 percent in light and 42 in dark, flat, drawn over the paving and under the sun's own shadows (no real-time shadow of a tree)
  const shadowMaterial = kit.adopt(new THREE.MeshBasicMaterial({ color: tones.shadow, transparent: true, opacity: palette.dark ? 0.42 : 0.09, depthWrite: false }));
  const trunks = kit.instanced(trunk, planted.length, group, { cast: false });
  const shadows = kit.instanced(shadow, planted.length, group, { cast: false, material: shadowMaterial });
  // one instanced mesh for each crown variant (the trunk and the shadow are the same for every tree): a tree is in the mesh of its variant
  const crowns = crownGeometries.map((geometry, variant) => kit.instanced(geometry, planted.filter((t) => t[3].variant === variant).length, group, { cast: false }));
  const filled = crowns.map(() => 0);
  const matrix = new THREE.Matrix4();
  const turn = new THREE.Quaternion();   // a tree is never turned: its facets were lit once, for the one camera (a variant is turned before its light is decided)
  planted.forEach(([x, z, size, look], i) => {
    const scale = new THREE.Vector3(size * look.width, size * look.height, size * look.width);
    matrix.compose(new THREE.Vector3(x, KERB + ABOVE, z), turn, scale);
    crowns[look.variant].setMatrixAt(filled[look.variant]++, matrix);
    trunks.setMatrixAt(i, matrix);
    matrix.compose(new THREE.Vector3(x + TREE.shadowShift[0] * size, KERB + ABOVE / 2 * 3, z + TREE.shadowShift[1] * size), turn, new THREE.Vector3(size, size, size));
    shadows.setMatrixAt(i, matrix);
  });
  for (const mesh of [...crowns, trunks, shadows]) mesh.instanceMatrix.needsUpdate = true;
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
