// The world (WP-9.11): the one scene of the City, the Building, the Floor and the Lobby. It is the prototype's single world: the lots, the streets,
// the trees and one tower per project, each tower's floors holding their rooms. A screen does not change scenes; it sets targets on this world
// (which building is open, which floor the person is on) and the world approaches them frame by frame: the building the person clicked opens where
// it stands while the camera flies in, the other floors of a building shrink to nothing when a floor is entered, and every step reverses. The other
// buildings and the city's furniture stay where they are, drawn, throughout. A model that differs in its words, in the state of a floor, or in the
// targets changes the world in place (`update`); only a change of the set of lots builds it again.
//
// model: {ready, selectedId, marked, outlined, focus, floor, frame, room, lots: [{id, name, accepted, decisions, runningTask, tip, sub, floors: [{name,
// label, state, window, decisions, lobby, notes: ["done" | "run" | "left"], documents, tip, interactive, plate}], selected, tag: {floor, text}|null}]}.
// `focus` is the building that is open; `floor` the floor of it the route is on (the Floor, the Lobby), with `room` the words of that room
// ({tips: {agent, doorTip}, board, door}); `frame` the one floor a phone shows; `marked` the id of the building that keeps its brackets in the City.
// What the pointer meets in a room (R-31): the owl (`agent`, or `tray` when it asks something: the Inbox), the board of notes (`tasks`) and the bookcase (`desk`), and in the
// Lobby the door (`lobby-door`); in the Building the floor (`floor:<name>`, R-28) and the Lobby's door (`door`). A hit's `marks` are the corner brackets the engine shows for it.

import { lotAt, buildGround } from "./city.js";
import { createTower, floorBox, lotBox, towerBox, towerStructure } from "./tower.js";
import { EXPLODE_RATE, approach } from "./prototype-motion.js";
import { boardNode, doorNode, plateNode, tagNode } from "./plates.js";
import { agentTip, asking, documentsTip, tasksTip } from "./room-words.js";

/** The page's City at 1280 by 800: a building's ledge, 7.1 by 5.5 units, is 212 px across on the screen, which is (7.1 + 5.5) * 0.7071 units of the camera's space. */
const CITY_PIXELS_A_UNIT = 212 / ((7.1 + 5.5) * Math.SQRT1_2);
const CITY_SMALLEST = 0.75;   // the phone's share of it: 87.3 px of a roof's edge against 116.4, in `city.html`
const EMPTY_FLOORS = 5;      // the floors of the building the empty City is framed on
const SETTLED = 0.004;       // a tower's open progress that is this near 0 or 1 is there (the prototype's `explode` snap)
const VIS_RATE = 8;          // the prototype's `f.vis += (target - vis) * (1 - exp(-dt * 8))`
const VIS_SETTLED = 0.01;

/** The words of a room's three objects and its door, from the model's own tips, the notes of the board and the documents on the shelves. */
function roomTips(floor, room) {
  const agent = (room.tips && room.tips.agent) || "";
  const documents = typeof floor.documents === "number" ? floor.documents : null;
  return {
    agent: agentTip(agent, false), tray: agentTip(agent, true), tasks: tasksTip(floor.notes, floor.plate && typeof floor.plate.left === "number" ? floor.plate.left : null), desk: documentsTip(documents),
    door: room.doorTip || "Control room · skills, costs, connections",
  };
}

/** The point over an object, for its tooltip: the middle of the top of its box in the world. */
export function topOf(THREE, object) {
  object.updateWorldMatrix(true, true);   // a room made a moment ago has not been rendered: its matrices are as stale as its parents' (as `pick.js` brings them up to date)
  const box = new THREE.Box3().setFromObject(object);
  return new THREE.Vector3((box.min.x + box.max.x) / 2, box.max.y, (box.min.z + box.max.z) / 2);
}

export function buildWorld(kit, model) {
  const { THREE } = kit;
  const group = new THREE.Group();
  const lots = model.lots;
  const ground = buildGround(kit, lots.length);
  group.add(ground.group);
  const towers = new Map();
  let focus = null;      // the building that is open: set by `setFocus` (the engine, or the test), never by the model alone
  let floorSel = null;   // the floor the route is on
  let frameSel = null;   // the one floor a phone shows
  let current = model;
  const structures = new Map();

  const content = {
    kind: "world", live: true, group, towers, hits: [], labels: [], beacons: [], markers: [], motions: [], outlines: [], brackets: [], tag: null,
    selected: model.outlined || null, marked: model.marked || null, intro: null,
  };

  function place(lot, i) {
    const { x, z } = lotAt(i, lots.length);
    const old = towers.get(lot.id);
    const tower = createTower(kit, lot, x, z);
    if (old) {
      tower.open = old.open;
      tower.target = old.target;
      tower.vis = lot.floors.map((f) => (old.vis[old.lot.floors.findIndex((o) => o.name === f.name)] !== undefined ? old.vis[old.lot.floors.findIndex((o) => o.name === f.name)] : 1));
      tower.visTarget = lot.floors.map((f) => (old.visTarget[old.lot.floors.findIndex((o) => o.name === f.name)] !== undefined ? old.visTarget[old.lot.floors.findIndex((o) => o.name === f.name)] : 1));
      group.remove(old.root, old.brackets.group);
      old.dispose();
      if (old.interior) tower.ensureInterior();
    }
    towers.set(lot.id, tower);
    group.add(tower.root, tower.brackets.group);   // the root is what the pointer picks (the tower and its marks); the brackets stand apart, so they are never picked
    structures.set(lot.id, JSON.stringify(towerStructure(lot)));
    tower.apply();
    return tower;
  }
  lots.forEach((lot, i) => place(lot, i));

  const floorIndex = (tower) => {
    const name = floorSel || frameSel;
    return name ? tower.lot.floors.findIndex((f) => f.name === name) : -1;
  };

  /** The floor targets: in the open building, the floor the person is on stays and the others go to nothing; everywhere else all are drawn. */
  function aimFloors() {
    // F1-D7: building.html draws no other building beside the open one (the Floor and the Lobby keep theirs, M-15): while a building is open and no floor of it is entered,
    // the others shrink to nothing as the floors of a building do, and come back with the floor
    const alone = Boolean(focus) && !floorSel;
    for (const tower of towers.values()) {
      const only = tower.id === focus ? floorIndex(tower) : -1;
      tower.visTarget = tower.lot.floors.map((f, i) => (tower.id !== focus ? (alone ? 0 : 1) : only < 0 || i === only ? 1 : 0));
      const hush = tower.id === focus && Boolean(floorSel);   // the Floor and the Lobby show the room alone: no mark beside it
      if (tower.marksHidden !== hush) {
        tower.marksHidden = hush;
        tower.apply();
      }
    }
  }

  /** Make the arrays the engine reads (hits, markers, motions, outlines, beacons) from the towers as they are now. */
  function collect() {
    const hits = [];
    const markers = [];
    const motions = [];
    const outlines = [];
    const beacons = [];
    const brackets = [];
    lots.forEach((lot, i) => {
      const tower = towers.get(lot.id);
      markers.push(...tower.markers);
      motions.push(...tower.motions);
      if (tower.interior && (focus === lot.id || tower.open > 0)) motions.push(...tower.roomMotions);   // an owl moves while its room is open or closing: the City ticks none after a visit
      outlines.push(...tower.outlines);
      brackets.push({ id: lot.id, group: tower.brackets.group, tower });
      if (tower.beacon) beacons.push(tower.beacon);
      if (focus === lot.id && tower.interior) {
        const only = floorSel ? tower.lot.floors.findIndex((f) => f.name === floorSel) : -1;
        const room = current.room || {};
        lot.floors.forEach((f, k) => {
          const parts = tower.parts[k];
          if (!f.interactive || !parts || tower.vis[k] <= VIS_SETTLED) return;
          if (only >= 0) {
            if (k !== only) return;
            // R-31: the room's ways in are what the pointer picks, and the room as a whole is not
            const words = roomTips(f, room);
            const asks = asking(f);
            if (parts.agent) hits.push({ object: parts.agent, id: asks ? "tray" : "agent", tip: asks ? words.tray : words.agent, marks: parts.marks.agent, anchor: topOf(THREE, parts.agent) });
            hits.push({ object: parts.board, id: "tasks", tip: words.tasks, marks: parts.marks.board, anchor: topOf(THREE, parts.board) });
            hits.push({ object: parts.shelf, id: "desk", tip: words.desk, marks: parts.marks.shelf, anchor: topOf(THREE, parts.shelf) });
            if (parts.door) hits.push({ object: parts.door, id: "lobby-door", tip: words.door, marks: parts.marks.door, anchor: topOf(THREE, parts.door) });
          } else {
            hits.push({ object: tower.floorGroups[k], id: `floor:${f.name}`, tip: f.tip, marks: parts.marks.room });   // R-28: the pointer meets the whole floor; its corners are marked
            if (parts.door) hits.push({ object: parts.door, id: "door", tip: "Control room · skills, costs, connections", marks: parts.marks.door });
          }
        });
      } else if (!focus && lot.floors.some((f) => f.interactive)) {
        hits.push({ object: tower.root, id: lot.id, tip: lot.tip, pad: 0.06, brackets: true });   // R-17: a building is marked by its brackets, not by an outline
      }
    });
    // F1: the brackets of a hit that is no longer one (a floor that opened into the Floor, an owl that left with a Back) are put away with it, whatever the pointer did
    const kept = new Set(hits.map((hit) => hit.marks).filter(Boolean));
    for (const hit of content.hits) if (hit.marks && !kept.has(hit.marks)) hit.marks.visible = false;
    for (const [key, list] of [["hits", hits], ["markers", markers], ["motions", motions], ["outlines", outlines], ["beacons", beacons], ["brackets", brackets]]) {
      content[key].length = 0;
      content[key].push(...list);
    }
    const focused = focus ? towers.get(focus) : null;
    content.dim = Boolean(focused && !focused.lot.accepted);   // a project that is not accepted: the whole drawing at 55 percent (the engine's canvas class)
    content.tag = focused && focused.tag ? { group: focused.tag.group, floor: focused.tag.floor, y: focused.tagRestY() } : null;
  }

  /** The words: the cards of the City, or the plates and the tag of the open building, the board and the door of a room, and every tooltip. */
  content.text = (m) => {
    const labels = [];
    const tips = new Map();
    m.lots.forEach((lot) => {
      const tower = towers.get(lot.id);
      if (!tower) return;
      tips.set(lot.id, lot.tip);
      for (const f of lot.floors) tips.set(`floor:${f.name}`, f.tip);
      if (!m.focus) {
        labels.push({
          id: lot.id, kind: "card", name: lot.name, decisions: lot.decisions, running: lot.runningTask !== null, sub: lot.sub,
          selected: lot.id === m.selectedId, accepted: lot.accepted, anchor: tower.cardAnchor, fitAnchor: tower.cardRestAnchor,
          quiet: m.lots.length >= 3 && lot.accepted && lot.decisions === 0 && lot.runningTask === null,
        });
      } else if (m.focus === lot.id) {
        const index = m.floor ? lot.floors.findIndex((f) => f.name === m.floor) : -1;
        if (index >= 0) {
          const room = m.room || {};
          const words = roomTips(lot.floors[index], room);
          tips.set("agent", words.agent);
          tips.set("tray", words.tray);
          tips.set("tasks", words.tasks);
          tips.set("desk", words.desk);
          tips.set("lobby-door", words.door);
          if (room.board) labels.push({ id: "board-label", kind: "board", rank: 0, title: room.board.title, lines: room.board.lines, dot: room.board.dot, decisions: 0, running: false, anchor: tower.boardAnchors[index], make: boardNode });
          if (room.door) labels.push({ id: "door-label", kind: "door", rank: 5, text: "Control room", decisions: 0, running: false, anchor: tower.doorAnchors[index], fit: tower.doorPlaques[index], shown: () => tower.open > 0.9 && tower.vis[index] > 0.999,   // the label ignores a floor's own scale, so it waits until the floor has its full size
           make: doorNode });
        } else {
          // a plate for each floor beside the building (desktop and tablet); the phone has the compact card in the corner instead, which is the page's
          if (!m.frame) {
            lot.floors.forEach((f, i) => {
              if (!f.interactive || !f.plate) return;
              labels.push({
                id: `floor:${f.name}`, kind: "plate", place: "column", plate: f.plate, selected: lot.selected === f.name,
                decisions: f.decisions, running: f.state === "working", anchor: tower.plateAnchors[i], make: () => plateNode(f.plate),
              });
            });
          }
          if (tower.tag && lot.tag) labels.push({ id: "tag", kind: "tag", rank: 1, text: lot.tag.text, decisions: 0, running: false, anchor: tower.tagAnchor, make: tagNode });
        }
      }
    });
    return { labels, tips };
  };

  /** The open building is the focus: its rooms are built and it starts to open (or close, for `null`). `instant` puts every tower there at once. */
  content.setFocus = (id, instant = false) => {
    focus = id || null;
    for (const tower of towers.values()) {
      tower.target = tower.id === focus ? 1 : 0;
      if (tower.target === 1) tower.ensureInterior();
    }
    aimFloors();
    if (instant) content.finish(); else collect();
  };

  /** The floor the route is on and the one floor a phone shows: the other floors of the open building go to nothing (or come back). */
  content.setFloors = (floor, frame, instant = false) => {
    floorSel = floor || null;
    frameSel = frame || null;
    aimFloors();
    if (instant) content.finish(); else collect();
  };

  const settled = (tower) => tower.open === tower.target && tower.vis.every((v, i) => v === tower.visTarget[i]);

  /** Move every tower and every floor toward its target by `dt` seconds, as the prototype moved `explode` and `vis`. Returns true while any is still moving. */
  content.step = (dt) => {
    let moving = false;
    for (const tower of towers.values()) {
      if (settled(tower)) continue;
      if (tower.open !== tower.target) {
        tower.open = approach(tower.open, tower.target, dt, EXPLODE_RATE);
        if (Math.abs(tower.open - tower.target) <= SETTLED) tower.open = tower.target; else moving = true;
      }
      tower.vis = tower.vis.map((v, i) => {
        if (v === tower.visTarget[i]) return v;
        const next = approach(v, tower.visTarget[i], dt, VIS_RATE);
        if (Math.abs(next - tower.visTarget[i]) <= VIS_SETTLED) return tower.visTarget[i];
        moving = true;
        return next;
      });
      tower.apply();
    }
    if (!moving) collect();   // a tower that has closed, opened or shrunk settles its hits
    return moving;
  };
  content.moving = () => [...towers.values()].some((t) => !settled(t));
  content.finish = () => {
    for (const tower of towers.values()) {
      tower.open = tower.target;
      tower.vis = [...tower.visTarget];
      tower.apply();
    }
    collect();
  };

  /**
   * Change the world to a model of the same lots, in place. Returns {rebuild, structure, inPlace, focus, floors}: `rebuild` when the lots are not the
   * same (the engine builds the world again), `structure` when a tower was made again (only when its floors or its acceptance changed), `inPlace` when a
   * tower's state, windows, decisions, sheets or drawers changed where they stand, `focus` when the open building changed, `floors` when the
   * floor the route is on (or a phone shows) changed.
   */
  content.update = (m) => {
    const same = m.lots.length === lots.length && m.lots.every((lot, i) => lot.id === lots[i].id);
    if (!same) return { rebuild: true };
    let structure = false;
    let inPlace = false;
    m.lots.forEach((lot, i) => {
      const key = JSON.stringify(towerStructure(lot));
      lots[i] = lot;
      if (structures.get(lot.id) !== key) {
        place(lot, i);
        structure = true;
      } else {
        const tower = towers.get(lot.id);
        if (tower.sync(lot)) inPlace = true;
        tower.setTag(lot.tag);
      }
    });
    current = m;
    content.selected = m.outlined || null;
    content.marked = m.marked || null;
    const focusChanged = (m.focus || null) !== focus;
    const floorsChanged = (m.floor || null) !== floorSel || (m.frame || null) !== frameSel;
    floorSel = m.floor || null;
    frameSel = m.frame || null;
    if (focusChanged) content.setFocus(m.focus || null);
    else {
      for (const tower of towers.values()) if (tower.target === 1) tower.ensureInterior();
      aimFloors();
      collect();
    }
    return { rebuild: false, structure, inPlace, focus: focusChanged, floors: floorsChanged };
  };

  /** The part of the world the camera frames: the floor the person is on, else the open building, else the whole City. */
  content.subject = () => {
    const tower = focus ? towers.get(focus) : null;
    if (!tower) {
      // the City is framed on its buildings, as large as the free rectangle lets them stand (`zoomCap` says how large the page draws one); the city round them is drawn
      // beyond every edge the camera can show (city.js)
      const box = new THREE.Box3();
      lots.forEach((lot, i) => {
        const { x, z } = lotAt(i, lots.length);
        box.union(lotBox(THREE, x, z, lot.floors.length));
      });
      // F1-D3: a City with no project is still the city (city.html draws its streets and blocks behind the line that says so): with no building there is no box to fit, so the camera
      // frames the one lot the ground is drawn round, at the height of a typical building
      if (box.isEmpty()) box.union(lotBox(THREE, lotAt(0, 1).x, lotAt(0, 1).z, EMPTY_FLOORS));
      return box;
    }
    const i = lots.findIndex((lot) => lot.id === focus);
    const { x, z } = lotAt(i, lots.length);
    const k = floorIndex(tower);
    if (k >= 0) return floorBox(THREE, x, z, k);
    return towerBox(THREE, x, z, lots[i].floors.length, 1);
  };

  /**
   * How close the camera may come, in pixels to a world unit, for a canvas of `size`: in the City, as large as `city.html` draws a building at 1280 by 800 (its ledge is 212 px
   * across for a ledge of 8.9 units of screen), scaled with the canvas down to three quarters of it, which is what the page's phone frames draw (a ledge of 87 px against
   * 116 for the same two projects); null for a building, a floor or a room, which fill the free rectangle.
   */
  content.zoomCap = (size) => (focus ? null : CITY_PIXELS_A_UNIT * Math.max(CITY_SMALLEST, Math.min(size.w / 1280, size.h / 800)));

  content.bounds = content.subject();
  content.focusId = () => focus;
  collect();
  content.labels = content.text(model).labels;
  return content;
}

/** What the world is made of, for a model: the lots in order (a tower's own structure is compared tower by tower). */
buildWorld.structure = (model) => ({ ready: model.ready, lots: model.lots.map((lot) => lot.id) });
