// A building of the world (WP-9.11): one tower of floors that is the same set of meshes in the City, while it opens, in the Building, on the Floor.
//
// Closed, as the City shows it (round 4, R-16 to R-21): on every floor a ledge, walls with their windows set back in the wall (glass, sill, jamb), on
// the ground floor a shop front, an entrance and a canopy on posts; a roof in the brand colour with a parapet and two units, and the beacon's ring
// while a task runs. A lit floor shows the agent as a shadow in the owl's outline at its windows; a floor that waits has the decision mark beside
// it. Inside each floor is its room (building.js, the next package's), built when the person first asks to open the building and kept hidden until
// it opens: it stands behind the opaque walls, so adding it changes no pixel. Opening is one number per tower, `open` from 0 to 1, approached frame
// by frame as the prototype's `explode` was: the floors separate (the pitch goes from P to P + GAP through a smoothstep), the walls, the ledges, the
// roof and the canopy fade out, and the room is left as the cutaway the Building shows. The same number run backwards closes the building. A floor
// has its own number too, `vis`, approached faster: the floors that are not the one the person is on scale to nothing and come back (the Floor, the
// Lobby, a phone's one floor). Nothing is rebuilt to open, to close or to go into a floor.
//
// The static pieces of a floor's shell are baked into two batches (kit.batch): the walls and the glass. The glass is one mesh a floor so a window's
// state is one repaint of its vertices; the shadows and the marks are separate meshes because they move.

import { BASE, D, FRAME, GAP, H, P, SLAB, W, anchors, fillFloor, floorY } from "./building.js";
import { agentPose, agentRest, alertPose } from "./city-motion.js";
import { cityTones } from "./palette.js";
import { bracketSet, decisionMark } from "./marks.js";
import { owlOutline } from "./owl.js";
import { smooth } from "./prototype-motion.js";
import { AZIMUTH, ELEVATION } from "./rig.js";

const clamp01 = (t) => Math.max(0, Math.min(1, t));

/**
 * The closed City is lower than the rooms are: the drawing's floor is 0.3 of the building's width, the rooms' (a figure, a desk) need 0.47. A
 * closed tower is the same meshes squashed to this much of its height, and it rises to its full height as the walls fade (progress `s` of the
 * opening, through the same smoothstep); nothing is built twice. The foot of the building stays on the block (BASE).
 */
export const CLOSED_SQUASH = 0.64;
export const squash = (s) => CLOSED_SQUASH + (1 - CLOSED_SQUASH) * smooth(clamp01(s / 0.55));
/** The world's y of a point at height `y` of an unsquashed tower, at open progress `s` (already read through the smoothstep). */
export const worldY = (y, s) => BASE + squash(s) * (y - BASE);
const TALL = 1 / CLOSED_SQUASH;   // what is drawn at the drawing's height, before the squash

// The shell's measures, at the building's size (the drawing's proportions: windows 5/7 of a floor's wall, the shop front 11/14, the door 6/7), so
// that they follow the height of a floor (building.js `H`, shared with the rooms) if the rooms change it.
const WALL = 0.14;          // a wall's thickness: the glass is set back this far
const OVER = 0.35;          // how far a ledge and the roof stand out
const SILL = H / 28;        // a window's foot above the floor's slab
const GLASS_H = (H * 5) / 7;
const STORE_FOOT = (H * 3) / 56;
const STORE_H = (H * 11) / 14;
const DOOR_H = (H * 6) / 7;
const ROOF_H = 0.5 * TALL;   // the roof's height in the drawing, before the squash
const RIM = 0.38;
const PIT = 0.26 * TALL;
const CANOPY = { x: -1.0, y: (H * 51) / 56, w: 2.6, d: 1.34, thick: 0.14, post: 0.1 };
const DOOR = [-1.66, -0.38];
const VIEW_AXIS = [-Math.cos(ELEVATION) * Math.sin(AZIMUTH), -Math.sin(ELEVATION), -Math.cos(ELEVATION) * Math.cos(AZIMUTH)];   // the camera's way, into the screen

/**
 * What a tower is made of, for a lot: which floors it has and whether it is accepted and running. Everything else a poll or the arrival of the
 * documents can change (the words, the state, the windows, the decisions, the notes of the board, the documents on the shelves, the floor the work order is on) changes the tower
 * in place (`tower.sync`): the tower is built again only when the projects or the agents change (specification, section 2 of the round-3 authority).
 */
export function towerStructure(lot) {
  return [lot.accepted, lot.runningTask !== null, lot.floors.map((f) => [f.name, f.lobby, f.interactive])];
}

/** The y of a tower's roof at open progress `s` (already read through the smoothstep). */
export function roofY(n, s) {
  return floorY(n - 1, P + GAP * s) + P;
}

/**
 * The bounds, in the world, of a tower at (cx, cz) with `n` floors at open progress `s`: closed, the footprint with its porch and the roof with its beacon; open, the rooms
 * (the roof is gone, the porch with it) with room for the decision mark beside them and over the top room's wall. The two are mixed as the walls fade.
 */
export function towerBox(THREE, cx, cz, n, s) {
  const k = clamp01(s / 0.7);
  const mix = (closed, open) => closed + (open - closed) * k;
  const top = mix(worldY(roofY(n, s), s) + 1.4, floorY(n - 1, P + GAP * s) + FRAME.Y(FRAME.wallTop) + 0.6);
  return new THREE.Box3(new THREE.Vector3(cx - W / 2 - mix(1.2, 0.9), 0, cz - D / 2 - mix(0.3, 0.3)), new THREE.Vector3(cx + W / 2 + mix(1.2, 0.9), top, cz + D / 2 + mix(1.7, 0.4)));
}

/**
 * The bounds, in the world, of the building a lot has as the City draws it, with no margin: its footprint with the ledges and the canopy, and its roof. The City's camera
 * is fitted on these (the page draws a building as large as the free rectangle lets it, not smaller for the room round it).
 */
export function lotBox(THREE, cx, cz, n) {
  return new THREE.Box3(new THREE.Vector3(cx - W / 2 - OVER, 0, cz - D / 2 - OVER), new THREE.Vector3(cx + W / 2 + OVER, worldY(roofY(n, 0), 0) + 0.2, cz + D / 2 + CANOPY.d));
}

/** The bounds of one floor (i) of a tower, open. */
export function floorBox(THREE, cx, cz, i) {
  const y = floorY(i);
  return new THREE.Box3(new THREE.Vector3(cx - W / 2 - 0.4, y - 0.3, cz - D / 2 - 0.3), new THREE.Vector3(cx + W / 2 + 0.4, y + P + 0.3, cz + D / 2 + 0.3));
}

/**
 * The openings of floor i, along the front wall (x) and the right wall (z): [{a, b, bottom, top, kind: "glass" | "door"}], each from `a` to `b`
 * along its wall and from `bottom` to `top` up it. An upper floor has four windows in front and three at the side; the ground floor a shop front:
 * three windows and the door in front, two windows at the side.
 */
export function openings(i) {
  const win = (c, width, bottom, height) => ({ a: c - width / 2, b: c + width / 2, bottom, top: bottom + height, kind: "glass" });
  if (i === 0) {
    const foot = SLAB + STORE_FOOT;
    const store = (a, b) => ({ a, b, bottom: foot, top: foot + STORE_H, kind: "glass" });
    return {
      front: [store(-2.56, -1.92), { a: DOOR[0], b: DOOR[1], bottom: SLAB, top: SLAB + DOOR_H, kind: "door" }, store(0.14, 1.3), store(1.48, 2.64)],
      right: [store(-1.85, -0.5), store(0.2, 1.55)],
    };
  }
  const foot = SLAB + SILL;
  return {
    front: [-2.1, -0.7, 0.7, 2.1].map((c) => win(c, 1.2, foot, GLASS_H)),
    right: [-1.4, 0, 1.4].map((c) => win(c, 1.2, foot, GLASS_H)),
  };
}

/**
 * Build a tower for `lot` ({id, name, accepted, runningTask, tip, floors, selected, tag, ...}) standing at (cx, cz). Returns the tower: its
 * group, the floors' groups, `open` (the progress), `vis` (each floor's) and the functions the world calls.
 */
export function createTower(kit, lot, cx, cz) {
  const { THREE, palette } = kit;
  const T = palette.T;
  const tones = cityTones(palette);
  const n = lot.floors.length;
  const root = new THREE.Group();       // what the pointer picks: the tower and what stands beside it, none of them squashed with it
  const group = new THREE.Group();
  group.position.set(cx, 0, cz);
  const overlay = new THREE.Group();    // the decision marks: beside the floors, at their own size, turning about the view axis
  overlay.position.set(cx, 0, cz);
  root.add(group, overlay);
  const floorGroups = [];
  const shells = [];
  const marks = [];            // the decision mark beside a floor that waits (or null)
  const markMotions = [];      // the notification of each mark, as the engine's motions: {tick(seconds), rest()}
  const agents = [];           // the shadows of a floor: {group, windows, on, fade, motion}, made when the floor is first lit
  const glassOf = [];          // each floor's glass mesh: its state is one repaint
  const roomLists = [];        // each room's own motions, markers and outlines, so that one room can be made again alone
  const bracketing = bracketSet(kit, BASE + 0.02);
  bracketing.group.position.set(cx, 0, cz);
  const tower = {
    id: lot.id, lot, root, group, overlay, n, floorGroups, open: 0, target: 0, interior: false,
    vis: lot.floors.map(() => 1), visTarget: lot.floors.map(() => 1),
    motions: [], roomMotions: [], markers: [], outlines: [], inner: [], parts: [], beacon: null, tag: null, brackets: bracketing,
    shown: lot.floors.map((f) => ({ state: f.state, window: f.window, decisions: f.decisions, notes: null, documents: null })),
    cardAnchor: new THREE.Vector3(cx, 0, cz), plateAnchors: [], boardAnchors: [], doorAnchors: [], tagAnchor: new THREE.Vector3(), marksHidden: false,
  };
  const fadeMats = [];
  const roofMats = [];
  const adopted = [];          // the materials this tower made, freed with it
  const adopt = (material) => {
    adopted.push(material);
    return kit.adopt(material);
  };

  // --- the colours a window can have ---------------------------------------------------------------------------------------------
  /** The glass of floor i: warm white while the floor is lit, else the project's glass, or the wall's own tone for a project that is not accepted. */
  const glassColour = (i, window) => {
    if (!lot.accepted) return tones.glassOff;
    if (window === "lit") return tones.glassLit;
    return i === 0 ? tones.store : tones.glass;
  };
  const paintGlass = (mesh, colour) => {
    const attribute = mesh.geometry.getAttribute("color");
    for (let k = 0; k < attribute.count; k++) attribute.setXYZ(k, colour.r, colour.g, colour.b);
    attribute.needsUpdate = true;
  };
  const lit = (f) => lot.accepted && f.window === "lit";
  const waits = (f) => lit(f) && f.state === "waiting" && f.decisions > 0;   // R-21: a mark stands only beside a lit floor that waits

  // --- the walls of a floor, pierced by its openings -----------------------------------------------------------------------------
  const wallTones = { top: tones.shell.top, left: tones.shell.left, right: tones.shell.right };
  /** One wall (axis "x": the front, "z": the right) from `from` to `to`, with piers between the openings, and the pieces under and over each. */
  function wall(batch, axis, from, to, list) {
    const piece = (u0, u1, y0, y1, toned) => {
      if (u1 - u0 < 1e-6 || y1 - y0 < 1e-6) return;
      if (axis === "x") batch.box(u1 - u0, y1 - y0, WALL, (u0 + u1) / 2, y0, D / 2 - WALL / 2, toned);
      else batch.box(WALL, y1 - y0, u1 - u0, W / 2 - WALL / 2, y0, (u0 + u1) / 2, toned);
    };
    const jamb = axis === "x" ? { ...wallTones, right: tones.jamb } : { ...wallTones, left: tones.jamb };   // the side of an opening the camera sees
    let cursor = from;
    for (const o of list) {
      piece(cursor, o.a, SLAB, SLAB + H, jamb);
      piece(o.a, o.b, SLAB, o.bottom, wallTones);
      piece(o.a, o.b, o.top, SLAB + H, wallTones);
      cursor = o.b;
    }
    piece(cursor, to, SLAB, SLAB + H, wallTones);
  }

  /** The shell of floor i: the ledge, the walls, the sills, the door and the canopy (one batch), the glass (another). */
  function buildShell(i, fg) {
    const shell = new THREE.Group();
    fg.add(shell);
    const open = openings(i);
    const walls = kit.batch();
    const glass = kit.batch();
    walls.box(W + 2 * OVER, SLAB, D + 2 * OVER, 0, 0, 0, tones.ledge);
    wall(walls, "x", -W / 2, W / 2, open.front);
    wall(walls, "z", -D / 2, D / 2 - WALL, open.right);
    const tint = glassColour(i, lot.floors[i].window);
    for (const o of open.front) {
      const plane = D / 2 - WALL + 0.005;
      if (o.kind === "door") {
        walls.front(o.a, o.bottom, o.b, o.top, plane, lot.accepted ? tones.door : tones.glassOff);
        continue;
      }
      glass.front(o.a, o.bottom, o.b, o.top, plane, tint);
      walls.box(o.b - o.a + 0.12, 0.12, 0.12, (o.a + o.b) / 2, o.bottom - 0.1, D / 2 + 0.06, tones.sill);
    }
    for (const o of open.right) {
      glass.side(o.a, o.bottom, o.b, o.top, W / 2 - WALL + 0.005, tint);
      walls.box(0.12, 0.12, o.b - o.a + 0.12, W / 2 + 0.06, o.bottom - 0.1, (o.a + o.b) / 2, tones.sill);
    }
    if (i === 0) {
      // the canopy over the entrance, on two posts at its front corners
      walls.box(CANOPY.w, CANOPY.thick, CANOPY.d, CANOPY.x, SLAB + CANOPY.y, D / 2 + CANOPY.d / 2, tones.unit);
      for (const dx of [-1, 1]) walls.box(CANOPY.post, CANOPY.y, CANOPY.post, CANOPY.x + dx * (CANOPY.w / 2 - 0.15), SLAB, D / 2 + CANOPY.d - 0.1, tones.post);
    }
    walls.mesh(shell);
    glassOf[i] = glass.mesh(shell, { cast: false });
    return shell;
  }

  // --- the agent's shadow at a lit floor's windows (R-19) ------------------------------------------------------------------------
  const outlineCache = new Map();
  /** The shadow figure for a window of `width` by `height`: the owl's body and two ear tufts, fitted to the window, in one geometry (body first, the ears just behind). */
  function figureGeometry(width, height) {
    const key = `${width.toFixed(2)}x${height.toFixed(2)}`;
    if (!outlineCache.has(key)) {
      const outline = owlOutline(THREE, { scaleX: (0.56 * width) / 160, scaleY: (0.82 * height) / 164 });
      const parts = [new THREE.ShapeGeometry(outline.body, 14), ...outline.ears.map((ear) => new THREE.ShapeGeometry(ear, 6).translate(0, 0, -0.004))];
      const position = [];
      for (const part of parts) {
        const flat = part.index ? part.toNonIndexed() : part;   // a shape's geometry may come indexed or not, according to the library
        position.push(...flat.getAttribute("position").array);
        if (flat !== part) flat.dispose();
      }
      const geometry = kit.track(new THREE.BufferGeometry());
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(position, 3));
      geometry.computeBoundingSphere();
      for (const part of parts) part.dispose();
      outlineCache.set(key, geometry);
    }
    return outlineCache.get(key);
  }

  /** The shadows of floor i, made when the floor first needs them: one figure at each window of its front wall, standing in the window's recess. */
  function ensureAgent(i) {
    if (agents[i]) return agents[i];
    const list = openings(i).front.filter((o) => o.kind === "glass");
    const holder = new THREE.Group();
    holder.visible = false;
    floorGroups[i].add(holder);
    const windows = list.map((o, k) => {
      const width = o.b - o.a;
      const height = o.top - o.bottom;
      const material = adopt(new THREE.MeshBasicMaterial({ color: tones.agent, transparent: true, opacity: 0, depthFunc: THREE.LessDepth, side: THREE.DoubleSide }));
      const mesh = new THREE.Mesh(figureGeometry(width, height), material);
      mesh.renderOrder = 2;   // after the glass it stands behind, whatever the sort says
      mesh.castShadow = false;
      const at = new THREE.Group();
      at.add(mesh);
      holder.add(at);
      return { at, material, centre: (o.a + o.b) / 2, foot: o.bottom, width, height, k };
    });
    const agent = { group: holder, windows, on: false, fade: 1 };
    const place = (w, pose) => {
      w.at.position.set(w.centre + pose.x * (w.width / 1.2), w.foot + 0.03 + pose.y * (w.height / GLASS_H), D / 2 - 0.1);
      w.at.scale.setScalar(Math.max(pose.scale, 0.001));
      w.material.opacity = pose.opacity * agent.fade;
    };
    agent.motion = {
      tick: (seconds) => { for (const w of windows) place(w, agentPose(seconds, w.k, i)); },
      rest: () => { for (const w of windows) place(w, agentRest(w.k)); },
    };
    agent.motion.rest();
    agents[i] = agent;
    return agent;
  }

  function setAgent(i, on) {
    if (!on && !agents[i]) return;
    const agent = ensureAgent(i);
    agent.on = on;
    agent.group.visible = on && agent.fade > 0.01;
  }

  // --- the decision mark beside a floor that waits (R-20, R-21) ------------------------------------------------------------------
  const markAt = [W / 2 + 0.45, 0.15, -D / 2 - 0.55];   // x, z beside the floor's right back corner; y over the slab's top
  const viewAxis = new THREE.Vector3(...VIEW_AXIS);
  /** The mark beside floor i: there while that floor is lit and waits for an answer in an accepted project, gone when it does not. */
  function setMark(i, on) {
    if (on && !marks[i]) {
      marks[i] = decisionMark(kit, overlay, markAt[0], 0, markAt[2]);
      marks[i].userData.baseY = 0;
      marks[i].userData.floor = i;
      markMotions[i] = {
        tick: (seconds) => {
          const pose = alertPose(seconds);
          marks[i].position.y = marks[i].userData.baseY + pose.rise;
          marks[i].quaternion.setFromAxisAngle(viewAxis, (pose.roll * Math.PI) / 180);   // a turn about the view axis is a turn in the picture
        },
        rest: () => {
          marks[i].position.y = marks[i].userData.baseY;
          marks[i].quaternion.identity();
        },
      };
    } else if (!on && marks[i]) {
      overlay.remove(marks[i]);
      marks[i] = null;
      markMotions[i] = null;
    }
  }

  // --- the closed shell of every floor --------------------------------------------------------------------------------------------
  lot.floors.forEach((f, i) => {
    const fg = new THREE.Group();
    fg.position.y = floorY(i, P);
    group.add(fg);
    floorGroups.push(fg);
    shells.push(buildShell(i, fg));
    if (lit(f)) setAgent(i, true);
    if (waits(f)) setMark(i, true);
  });

  // --- the roof (it fades with the opening and does not come back: the top floor's room is open like the others) ----------------------------
  const roof = new THREE.Group();
  group.add(roof);
  {
    const body = kit.batch();
    const wr = W + 2 * OVER;
    const dr = D + 2 * OVER;
    body.front(-wr / 2, 0, wr / 2, ROOF_H, dr / 2, tones.roof.left);
    body.side(-dr / 2, 0, dr / 2, ROOF_H, wr / 2, tones.roof.right);
    body.flat(-wr / 2, dr / 2 - RIM, wr / 2, dr / 2, ROOF_H, tones.roof.top);
    body.flat(-wr / 2, -dr / 2, wr / 2, -dr / 2 + RIM, ROOF_H, tones.roof.top);
    body.flat(-wr / 2, -dr / 2 + RIM, -wr / 2 + RIM, dr / 2 - RIM, ROOF_H, tones.roof.top);
    body.flat(wr / 2 - RIM, -dr / 2 + RIM, wr / 2, dr / 2 - RIM, ROOF_H, tones.roof.top);
    body.flat(-wr / 2 + RIM, -dr / 2 + RIM, wr / 2 - RIM, dr / 2 - RIM, ROOF_H - PIT, tones.roofFloor);
    body.front(-wr / 2 + RIM, ROOF_H - PIT, wr / 2 - RIM, ROOF_H, -dr / 2 + RIM, tones.roofIn.left);
    body.side(-dr / 2 + RIM, ROOF_H - PIT, dr / 2 - RIM, ROOF_H, -wr / 2 + RIM, tones.roofIn.right);
    body.box(1.4, 0.64 * TALL, 1.1, 0.9, ROOF_H - PIT, -0.9, tones.unit);
    body.box(0.95, 0.44 * TALL, 0.8, 1.9, ROOF_H - PIT, 0.7, tones.unit);
    body.mesh(roof);
    if (lot.runningTask !== null && lot.accepted) {
      const material = adopt(new THREE.MeshBasicMaterial({ color: tones.beacon, transparent: true, opacity: 1 }));
      const ring = new THREE.Mesh(kit.track(new THREE.TorusGeometry(0.95, 0.07, 6, 28)), material);
      ring.rotation.x = Math.PI / 2;
      ring.position.set(-1.2, ROOF_H - PIT + 0.06, 1.0);
      roof.add(ring);
      const core = new THREE.Mesh(kit.track(new THREE.CylinderGeometry(0.32, 0.32, 0.05, 16)), adopt(new THREE.MeshBasicMaterial({ color: tones.beacon })));
      core.position.set(-1.2, ROOF_H - PIT + 0.03, 1.0);
      roof.add(core);
      tower.beacon = { ring, material, id: lot.id, fade: 1 };
    }
  }

  // The building's outline is its silhouette: one enclosing body from the ground to the roof (a floor's walls, its windows and the roof's parts are
  // inside the line, not drawn as lines of their own: the City's outline had a line at every floor boundary). The body is not drawn (its material is
  // invisible); it follows the height of the stack. A floor of the open building is outlined by its own room's slab and walls (building.js). The
  // City marks a building with corner brackets instead (R-17: `tower.brackets`), so the City draws no outline of it.
  const silhouette = new THREE.Mesh(kit.unitBox, adopt(new THREE.MeshBasicMaterial({ visible: false })));
  silhouette.userData.shell = true;
  silhouette.castShadow = false;
  group.add(silhouette);
  tower.silhouette = silhouette;

  // The walls, the ledges, the canopy and the roof fade as the building opens: each has materials of its own (a clone of the kit's shared one,
  // same tone), so fading this tower touches no other. A list takes its own clone of each material.
  const own = new Map();
  const ownOf = (base, list) => {
    if (!own.has(list)) own.set(list, new Map());
    const clones = own.get(list);
    if (!clones.has(base)) {
      const clone = adopt(base.clone());   // freed with the tower
      clone.transparent = true;
      clones.set(base, clone);
      list.push(clone);
    }
    return clones.get(base);
  };
  const claim = (root, list) => root.traverse((node) => {
    if (!node.material || node === (tower.beacon && tower.beacon.ring)) return;
    node.material = ownOf(node.material, list);
  });
  shells.forEach((shell) => claim(shell, fadeMats));
  claim(roof, roofMats);
  const setOpacity = (list, value) => {
    for (const m of list) {
      m.opacity = value;
      m.depthWrite = value >= 0.999;
    }
  };

  // --- the room of every floor, when the building is first asked to open --------------------------------------------------------------
  // The work-order tag stands on a floor of the open building: made when the rooms are, moved when the work order moves.
  tower.setTag = (tag) => {
    const index = tag ? tower.lot.floors.findIndex((f) => f.name === tag.floor) : -1;
    if (!tower.interior || index < 0) {
      if (tower.tag && index < 0) {
        group.remove(tower.tag.group);
        tower.tag = null;
      }
      return;
    }
    if (!tower.tag) {
      // R-29: the work-order tag is an HTML badge (plates.js `tagNode`) at the floor's left corner; the group is what the engine moves between floors and holds no mesh
      const mark = new THREE.Group();
      group.add(mark);
      tower.tag = { group: mark, floor: tag.floor, index };
    }
    tower.tag.floor = tag.floor;
    tower.tag.index = index;
    tower.apply();
  };

  /** The room of floor i, from the lot as it is now (made once, or again when the agent's state changed: the owl takes its pose, the floor its tone). The old room is freed. */
  function buildRoom(i) {
    const L = tower.lot;
    const f = L.floors[i];
    const inner = tower.inner[i];
    if (tower.parts[i]) tower.parts[i].dispose();
    inner.clear();
    const lists = { motions: [], markers: [], outlines: [] };
    roomLists[i] = lists;
    const drawn = { ...f, notes: Array.isArray(f.notes) ? f.notes : [], documents: typeof f.documents === "number" ? f.documents : 0 };   // unread: no binder yet
    tower.parts[i] = fillFloor(kit, inner, drawn, { lot: L.id, accepted: L.accepted, ...lists });
    Object.assign(tower.shown[i], { state: f.state, window: f.window, decisions: f.decisions, notes: JSON.stringify(drawn.notes), documents: drawn.documents });
    refreshLists();
  }

  /** The lists the engine reads (markers, motions, outlines) are the City's own (the notifications, the shadows) and each room's; a room's motions are kept apart (`roomMotions`). */
  function refreshLists() {
    tower.markers.length = 0;
    tower.motions.length = 0;
    tower.roomMotions.length = 0;
    tower.outlines.length = 0;
    for (const motion of markMotions) if (motion) tower.motions.push(motion);
    for (const agent of agents) if (agent && agent.on) tower.motions.push(agent.motion);
    for (const lists of roomLists) {
      if (!lists) continue;
      tower.markers.push(...lists.markers);
      tower.roomMotions.push(...lists.motions);   // the owls: the world takes them only while the room is the open one
      tower.outlines.push(...lists.outlines);
    }
  }

  tower.ensureInterior = () => {
    if (tower.interior) return false;
    tower.interior = true;
    tower.lot.floors.forEach((f, i) => {
      const inner = new THREE.Group();
      inner.visible = tower.open > 0;
      floorGroups[i].add(inner);
      tower.inner[i] = inner;
      if (f.interactive) buildRoom(i);
    });
    tower.setTag(tower.lot.tag);
    tower.apply();
    return true;
  };

  /**
   * The tower takes the words and the state of `next` (the same floors): everything a poll or the arrival of the documents changes is changed where
   * it stands, never by building the tower again. A window is repainted, the shadows come or go with the light, the board its notes, the bookcases their
   * binders, the decision mark comes or goes. Only a change of an agent's state makes that one room again (the owl takes another pose, the floor another tone).
   * A floor whose notes or documents are not known yet (`notes` or `documents` null) keeps what it shows. Returns true when anything changed.
   */
  tower.sync = (next) => {
    tower.lot = next;
    let changed = false;
    next.floors.forEach((f, i) => {
      const shown = tower.shown[i];
      const parts = tower.interior ? tower.parts[i] : null;
      if (f.window !== shown.window) {
        paintGlass(glassOf[i], glassColour(i, f.window));
        if (parts) parts.setWindow(f.window);
        shown.window = f.window;
        changed = true;
      }
      if (lit(f) !== Boolean(agents[i] && agents[i].on)) {
        setAgent(i, lit(f));
        refreshLists();
        changed = true;
      }
      if (waits(f) !== Boolean(marks[i])) {
        setMark(i, waits(f));
        refreshLists();
        changed = true;
      }
      if (!parts) {
        shown.state = f.state;
        shown.decisions = f.decisions;
        return;
      }
      if (f.state !== shown.state) {
        buildRoom(i);
        changed = true;
        return;
      }
      if (f.decisions !== shown.decisions) {   // the hit of the owl (the Inbox when it asks) and the mark follow; nothing is drawn again
        shown.decisions = f.decisions;
        changed = true;
      }
      if (Array.isArray(f.notes) && JSON.stringify(f.notes) !== shown.notes) {
        parts.setNotes(f.notes);
        shown.notes = JSON.stringify(f.notes);
        changed = true;
      }
      if (typeof f.documents === "number" && f.documents !== shown.documents) {
        parts.setDocuments(f.documents);
        shown.documents = f.documents;
        changed = true;
      }
    });
    if (changed) tower.apply();
    return changed;
  };

  /**
   * Free what this tower made, so that a tower made again (a task starts or ends: `world.place`) leaves nothing behind: every geometry in its tree and
   * in its brackets (the kit's shared unit box and edges are not its to free), the shadows' figures, and the materials it made. What the kit caches and
   * shares (its lit and unlit colours, the vertex-colour material) stays with the kit.
   */
  tower.dispose = () => {
    for (const parts of tower.parts) if (parts) parts.dispose();
    const seen = new Set();
    for (const top of [root, bracketing.group]) {
      top.traverse((node) => {
        if (node.geometry && !seen.has(node.geometry)) {
          seen.add(node.geometry);
          kit.release(node.geometry);
        }
      });
    }
    for (const geometry of outlineCache.values()) if (!seen.has(geometry)) kit.release(geometry);
    outlineCache.clear();
    for (const material of adopted) kit.free(material);
    adopted.length = 0;
  };

  // --- the opening: every position, every fade, from one number --------------------------------------------------------------------------
  /** Put the tower in the state of `tower.open` and of each floor's `vis`. */
  tower.apply = () => {
    const s = smooth(tower.open);
    const pitch = P + GAP * s;
    const sy = squash(s);
    group.scale.y = sy;                      // R-16: closed, the building is the drawing's height; it rises to the rooms' as the walls fade
    group.position.y = BASE * (1 - sy);      // its foot stays on the block
    floorGroups.forEach((g, i) => {
      g.position.y = floorY(i, pitch);
      g.scale.setScalar(Math.max(tower.vis[i], 0.001));
      g.visible = tower.vis[i] > 0.01;
    });
    roof.position.y = roofY(n, s);
    const bodyTop = roofY(n, s) + 0.3;
    silhouette.scale.set(W + 0.2, bodyTop - BASE, D + 0.2);
    silhouette.position.set(0, BASE + (bodyTop - BASE) / 2, 0);
    const fade = 1 - clamp01(s / 0.55);
    const roofFade = 1 - clamp01(s / 0.7);
    setOpacity(fadeMats, fade);
    setOpacity(roofMats, roofFade);
    shells.forEach((shell) => { shell.visible = fade > 0.01; });
    roof.visible = roofFade > 0.01 && tower.vis[n - 1] > 0.01;
    if (tower.beacon) tower.beacon.fade = roofFade;
    for (const agent of agents) {
      if (!agent) continue;
      agent.fade = fade;
      agent.group.visible = agent.on && fade > 0.01;
    }
    marks.forEach((mark, i) => {
      if (!mark) return;
      mark.userData.baseY = worldY(floorY(i, pitch) + SLAB, s) + markAt[1];   // beside its floor, at its own size, in the open building as in the City
      mark.visible = tower.vis[i] > 0.01 && !tower.marksHidden;               // the Floor and the Lobby show the room alone
      mark.position.y = mark.userData.baseY;   // the motion adds its rise on its next frame
    });
    tower.brackets.roof.position.y = worldY(roofY(n, s), s) + ROOF_H * sy;
    tower.brackets.closed = s < 0.01;
    tower.inner.forEach((inner) => { if (inner) inner.visible = tower.open > 0; });
    if (tower.tag) {
      tower.tag.group.position.set(-W / 2 + 0.6, floorY(tower.tag.index, pitch) + SLAB, D / 2 - 0.5);
      tower.tagAnchor.set(cx - W / 2 + 0.6, worldY(floorY(tower.tag.index, pitch) + SLAB, s) + 0.45, cz + D / 2 - 0.5);
    }
    tower.lot.floors.forEach((f, i) => {
      const y = worldY(floorY(i, pitch), s);
      (tower.plateAnchors[i] = tower.plateAnchors[i] || new THREE.Vector3()).set(cx + W / 2 + 0.2, y + 1.2, cz - D / 2);
      const a = anchors();
      (tower.boardAnchors[i] = tower.boardAnchors[i] || new THREE.Vector3()).set(cx + a.board.x, y + a.board.y, cz + a.board.z);
      (tower.doorAnchors[i] = tower.doorAnchors[i] || new THREE.Vector3()).set(cx + a.door.x, y + a.door.y, cz + a.door.z);
    });
    tower.cardAnchor.set(cx, worldY(roofY(n, s), s) + 1.6, cz);
  };

  /** The y the work-order tag rests at when the building is open: where the tag goes to, whatever the progress now. */
  tower.tagRestY = () => (tower.tag ? floorY(tower.tag.index, P + GAP) + SLAB : null);
  refreshLists();
  tower.apply();
  return tower;
}
