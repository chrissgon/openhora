// The Control room's small scene (R-51, `control-room.html`): a server room drawn in the City's style, every object a fact. Three racks of seven units, each with the fact's light
// (the `connections` facts: each class, then each secret, then the image; success lit, error when missing, dim when the unit carries none), a wall screen with a capped bar for each
// of the runs of the last seven days (`costs.rows` summed by day, as a share of the largest day), and the console, which carries no data and is the way into Skills. No plant: it
// carried no fact. The object of the open tab wears corner brackets (the console on Skills, the wall screen on Costs, the racks on Connections) and each object has the dark tooltip;
// a click opens the tab that holds the same facts as HTML. The room is static: nothing in it moves, and there is no label and no text in 3D.
//
// What it shows is worked out by sceneModel in control-model.js (pure, tested under Node); the builder takes the engine's kit, as the City's does, and registers itself as the scene
// kind "server" through the engine's BUILDERS: the engine names no server-room builder, and adding a scene kind adds a builder here, not a case there. The measures are the page's, in `scene/server-room.js`; the tones are `roomTones` and `serverTones`
// (palette.js), recipes of the page's `scene.css`; the statics are baked into a few batches (kit.batch): one for the shell, one for each rack, the wall screen and the console.

import { buildGround, KERB } from "../scene/city.js";
import { BUILDERS } from "../scene/engine.js";
import { boxBrackets, planeBrackets } from "../scene/marks.js";
import { roomTones, serverTones } from "../scene/palette.js";
import { pageBatch } from "../scene/room-frame.js";
import { BRACKETS, FRAME, LEDGE, ROOM, consoleDesk, rack, shell, tray, wallScreen } from "../scene/server-room.js";
import { topOf } from "../scene/world.js";
import { RACKS, UNITS } from "./control-model.js";

/** The canvas width under which the room wears no brackets: the phone (the page's phone frames draw none). */
export const MARKS_MIN_WIDTH = 900;

/** The page draws brackets once the room has been read, and also on "A read that failed" (B3-5: `failed`, which the view sets); not while it loads or waits for the configuration. */
const marksShown = (m) => Boolean(m.ready || m.failed);

/** Build the server room. model: sceneModel(). Returns what the engine needs, like buildCity: the group, the hits (each with its tooltip, the place of it and its brackets), `open`, `subject`. */
export function buildServer(kit, model) {
  const { THREE, palette } = kit;
  const tones = { ...roomTones(palette), ...serverTones(palette) };
  const group = new THREE.Group();
  group.add(buildGround(kit, 1).group);     // the block the room stands on and the streets round it, as the page draws them
  const room = new THREE.Group();
  room.position.y = KERB;
  group.add(room);
  const make = (batch) => pageBatch(batch, FRAME);
  const baked = (draw, parent) => {
    const batch = kit.batch();
    draw(make(batch));
    return batch.mesh(parent, { cast: false });
  };
  // the brackets of an object: solids in the brand colour, built hidden and shown by the engine; drawn, never picked
  const holder = (mesh) => {
    const marks = new THREE.Group();
    marks.visible = false;
    marks.userData.brackets = true;
    marks.add(mesh);
    room.add(marks);
    return marks;
  };
  const tone = tones.bracket;

  baked((pb) => { shell(pb, tones); tray(pb, tones); }, room);

  const hits = [];
  const racksMarks = holder(boxBrackets(kit, make, { ...BRACKETS.racks, tone }));
  RACKS.forEach((spec, r) => {
    const object = new THREE.Group();
    room.add(object);
    // the first fact is on the top unit of the first rack: the unit u from the bottom has the light of fact r * 7 + (6 - u)
    const lights = Array.from({ length: UNITS }, (_, u) => model.leds[r * UNITS + (UNITS - 1 - u)]);
    baked((pb) => rack(pb, tones, r, lights), object);
    hits.push({ object, id: spec.id, tip: model.racks[r].tip, marks: racksMarks, anchor: topOf(THREE, object) });
  });

  const wall = new THREE.Group();
  room.add(wall);
  baked((pb) => wallScreen(pb, tones, model.bars), wall);
  hits.push({ object: wall, id: "wall", tip: model.tips.wall, marks: holder(planeBrackets(kit, make, { ...BRACKETS.wall, tone })), anchor: topOf(THREE, wall) });

  const desk = new THREE.Group();
  room.add(desk);
  baked((pb) => consoleDesk(pb, tones), desk);
  hits.push({ object: desk, id: "console", tip: model.tips.console, marks: holder(boxBrackets(kit, make, { ...BRACKETS.console, tone })), anchor: topOf(THREE, desk) });

  // the part of the scene the camera frames: the room with its slab, not the city round it
  const subject = () => new THREE.Box3(
    new THREE.Vector3(FRAME.X(LEDGE.x0), KERB, FRAME.Z(LEDGE.z0)),
    new THREE.Vector3(FRAME.X(LEDGE.x0 + LEDGE.w), KERB + FRAME.Y(ROOM.h), FRAME.Z(LEDGE.z0 + LEDGE.d)),
  );

  // the words (the tooltips; there is no label) and the object of the open tab: a model with the same structure changes them without building the room again
  const text = (m) => ({ labels: [], tips: new Map([...m.racks.map((r) => [r.id, r.tip]), ["wall", m.tips.wall], ["console", m.tips.console]]), open: m.open || [], noMarks: !marksShown(m) });
  // the page draws no brackets on its phone frames (under 900 px, the phone's layout: `marksMinWidth`) nor while the room is loading or waiting for the configuration (`noMarks`: nothing is read), and the pointer's
  // brackets stand down with them
  return { group, hits, labels: [], beacons: [], markers: [], outlines: [], selected: null, open: model.open || [], noMarks: !marksShown(model), marksMinWidth: MARKS_MIN_WIDTH, subject, text };
}

/** What the room is made of, for a model: the LEDs and the bars; the tooltips, the label and the open tab are words. */
buildServer.structure = (model) => ({ ready: model.ready, leds: model.leds, bars: model.bars });

BUILDERS.server = buildServer;
